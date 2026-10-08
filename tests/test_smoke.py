import pytest
from conftest import full_marks

from app.agents.safety import SafetyVerdict
from app.rubric import (
    CATEGORY_MAX,
    RUBRIC,
    QuestionScore,
    ReviewOutput,
    category_totals,
    final_score_out_of_10,
)
from app.state import ExecutionDecision, PullRequest
from app.workflow import build_graph

PR = PullRequest(repo="o/r", number=1, title="t", diff="+print(1)")


def run():
    return build_graph().invoke({"pr": PR})


def test_rubric_totals():
    assert sum(CATEGORY_MAX.values()) == 100
    assert CATEGORY_MAX["Correctness"] == 30


def test_accepts_on_perfect_review(fake_llm):
    out = run()
    assert out["status"] == "accepted"
    assert out["score"] == 10.0
    assert out["iteration"] == 0


def test_score_is_computed_in_code_not_by_llm():
    out = full_marks(0.5)
    assert category_totals(out.question_scores)["Correctness"] == 15
    assert final_score_out_of_10(out.question_scores) == sum(s.score for s in out.question_scores) / 10
    assert "score" not in ReviewOutput.model_fields


def test_unsafe_pr_stops_early(fake_llm):
    fake_llm.outputs[SafetyVerdict] = SafetyVerdict(safe=False, reasons=["miner"])
    out = run()
    assert out["status"] == "rejected_unsafe"
    assert "review" not in out


def test_no_execution_skips_compile_test(fake_llm):
    fake_llm.outputs[ExecutionDecision] = ExecutionDecision(should_execute=False)
    out = run()
    assert "execution" not in out
    assert out["status"] == "accepted"


def test_constant_low_score_is_stagnation(fake_llm):
    fake_llm.outputs[ReviewOutput] = full_marks(0.3)
    out = run()
    assert out["status"] == "human_review"
    assert out["iteration"] == 1


def test_missing_question_rejected(fake_llm):
    bad = full_marks()
    bad.question_scores.pop()
    fake_llm.outputs[ReviewOutput] = bad
    with pytest.raises(ValueError, match="missing"):
        run()


def test_out_of_range_score_rejected(fake_llm):
    bad = full_marks()
    bad.question_scores[0] = QuestionScore(id="C1", score=99, justification="x")
    fake_llm.outputs[ReviewOutput] = bad
    with pytest.raises(ValueError, match="above max"):
        run()


def test_pr_content_is_delimited_as_untrusted(fake_llm):
    run()
    _, messages = fake_llm.calls[0]
    assert "UNTRUSTED" in messages[0][1] and "<pr>" in messages[1][1]


# ---- scoring engine & loop ------------------------------------------------

from conftest import review_with_total  # noqa: E402
from app.scoring import decide_next  # noqa: E402


def test_improving_scores_6_9_7_6_8_3_then_accept(fake_llm):
    fake_llm.outputs[ReviewOutput] = [review_with_total(t) for t in (69, 76, 83)]
    out = run()
    assert out["score_history"] == [6.9, 7.6, 8.3]
    assert out["score"] == 8.3
    assert out["iteration"] == 2  # two fix rounds
    assert out["status"] == "accepted"
    assert out["category_totals"] == {
        "Correctness": 30, "Code Quality": 20, "Security": 20,
        "Testing & Validation": 13, "Maintainability": 0,
    }
    print("\nscore_history:", out["score_history"], "->", out["status"].upper())


def test_exactly_threshold_accepts(fake_llm):
    fake_llm.outputs[ReviewOutput] = review_with_total(80)
    assert run()["status"] == "accepted"


def test_stagnation_routes_to_human_review(fake_llm):
    fake_llm.outputs[ReviewOutput] = [review_with_total(t) for t in (69, 70)]
    out = run()
    assert out["score_history"] == [6.9, 7.0]
    assert out["status"] == "human_review"
    assert out["iteration"] == 1


def test_regression_routes_to_human_review(fake_llm):
    fake_llm.outputs[ReviewOutput] = [review_with_total(t) for t in (69, 60)]
    assert run()["status"] == "human_review"


def test_slow_steady_progress_hits_max_iterations(fake_llm):
    fake_llm.outputs[ReviewOutput] = [review_with_total(t) for t in (40, 45, 50, 55, 60, 65)]
    out = run()
    assert out["status"] == "max_iterations"
    assert out["iteration"] == 5
    assert len(out["score_history"]) == 6


def test_decide_next_priority():
    kw = dict(threshold=8, max_iterations=5, min_improvement=0.3)
    assert decide_next([6.9], 0, **kw) == "fix"  # first score can't stagnate
    assert decide_next([7.0, 8.0], 5, **kw) == "accepted"  # accept beats max
    assert decide_next([7.0, 7.1], 5, **kw) == "human_review"


# ---- GitHub + compiler/test tool wired into the graph ----------------------

from app.config import get_settings  # noqa: E402


@pytest.fixture
def exec_on(monkeypatch):
    monkeypatch.setenv("ENABLE_TEST_EXECUTION", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_real_runner_in_graph(fake_llm, exec_on):
    pr = PullRequest(
        repo="o/r", number=1, title="calc",
        files={
            "calc.py": "def add(a, b):\n    return a - b\n",  # bug
            "test_calc.py": "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        },
        changed_files=["calc.py"],
    )
    out = build_graph().invoke({"pr": pr})
    assert out["execution"].passed is False
    assert "pytest: FAILED" in out["execution"].output
    # the review agent was shown the real failure output
    review_prompt = [m for s, m in fake_llm.calls if s is ReviewOutput][0][1][1]
    assert "pytest: FAILED" in review_prompt


def test_review_prompt_requires_question_scores_for_every_rubric_question():
    from app.agents.review import SYSTEM

    assert "question_scores" in SYSTEM and "comments" in SYSTEM
    assert f"all {len(RUBRIC)}" in SYSTEM
    for q in RUBRIC:
        assert f"{q.id} [0-{q.max_points}]" in SYSTEM
