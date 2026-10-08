from conftest import review_with_total

from app.agents.fix import build_fix_prompt
from app.fixes import apply_fix
from app.nodes import route_after_apply
from app.rubric import ReviewOutput
from app.state import ExecutionResult, FileEdit, FixOutput, PullRequest, ReviewResult
from app.workflow import build_graph

PR = PullRequest(
    repo="o/r", number=1, title="Add calc", description="add() must add",
    changed_files=["calc.py"],
    files={"calc.py": "def add(a, b):\n    return a - b\n", "other.py": "X = 1\n"},
)


def fix(*edits):
    return FixOutput(summary="s", edits=[FileEdit(path=p, content=c) for p, c in edits])


def test_applies_edit_to_changed_file():
    new, applied, rejected = apply_fix(PR, fix(("calc.py", "def add(a, b):\n    return a + b\n")))
    assert applied == ["calc.py"] and not rejected
    assert new.files["calc.py"].endswith("a + b\n")
    assert PR.files["calc.py"].endswith("a - b\n")  # original untouched


def test_rejects_unrelated_file_and_traversal():
    new, applied, rejected = apply_fix(PR, fix(
        ("other.py", "X = 2\n"), ("../evil.py", "x"), ("/etc/passwd", "x"), ("C:/x.py", "x"),
    ))
    assert applied == []
    assert rejected["other.py"].startswith("not a file changed")
    assert set(rejected) == {"other.py", "../evil.py", "/etc/passwd", "C:/x.py"}
    assert new.files == PR.files


def test_new_test_file_allowed_and_tracked():
    new, applied, _ = apply_fix(PR, fix(("tests/test_calc.py", "def test_x():\n    pass\n")))
    assert applied == ["tests/test_calc.py"]
    assert "tests/test_calc.py" in new.changed_files


def test_noop_edit_rejected():
    _, applied, rejected = apply_fix(PR, fix(("calc.py", PR.files["calc.py"])))
    assert applied == [] and rejected["calc.py"] == "no change"


def test_fix_prompt_contains_everything():
    state = {
        "pr": PR, "score": 6.9, "score_history": [6.9],
        "review": ReviewResult(
            question_scores=review_with_total(69).question_scores, comments=["add() subtracts"]
        ),
        "execution": ExecutionResult(
            ran=True, passed=False, compile_output="py_compile: OK", test_output="pytest: FAILED boom"
        ),
    }
    p = build_fix_prompt(state)
    for expected in (
        "return a - b",                 # current code
        "add() must add",               # PR requirement
        "add() subtracts",              # review feedback
        "scored", "Maintainability",    # failed rubric questions
        "py_compile: OK",               # compiler output
        "pytest: FAILED boom",          # test output
        "6.9",                          # previous score
    ):
        assert expected in p, expected
    assert "X = 1" not in p  # unrelated file is not shown


def test_route_after_apply():
    assert route_after_apply({"fix_log": [{"applied": ["a.py"]}]}) == "compile_test"
    assert route_after_apply({"fix_log": [{"applied": []}]}) == "human_review"


def test_unappliable_fix_goes_to_human_review(fake_llm):
    fake_llm.outputs[ReviewOutput] = [review_with_total(60)]
    fake_llm.outputs[FixOutput] = [fix(("unrelated.py", "x = 1\n"))]
    out = build_graph().invoke({"pr": PR})
    assert out["status"] == "human_review"
    assert out["fix_log"][0]["rejected"]
    assert len(out["score_history"]) == 1  # no pointless re-review


def test_buggy_demo_end_to_end():
    from demo.buggy_demo import run

    out = run(verbose=False)
    assert out["status"] == "accepted"
    assert out["score_history"] == [4.5, 6.9, 9.0]
    assert out["iteration"] == 2
    assert out["fix_log"][1]["rejected"] == {"setup.py": "not a file changed by this PR or a test file"}
    assert out["pr"].files["setup.py"] == "# unrelated\n"
    assert "pytest: OK" in out["execution"].output
