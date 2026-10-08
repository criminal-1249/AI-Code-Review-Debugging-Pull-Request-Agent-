"""End-to-end demo: intentionally buggy Python goes through the full review/fix loop.

Run:  python -m demo.buggy_demo

NO LLM KEY IS NEEDED: the LLM is replaced by a scripted stand-in that reacts to the REAL
compiler/pytest output it is shown. Everything else is the real system: the LangGraph
workflow, apply-fix validation, py_compile + pytest in a temp dir, and deterministic scoring.
"""
import difflib
import os
import sys

from app.agents import analysis, execution, fix, review, safety
from app.agents.safety import SafetyVerdict
from app.config import get_settings
from app.log import setup_logging
from app.rubric import RUBRIC, QuestionScore, ReviewOutput
from app.state import AnalysisResult, ExecutionDecision, FileEdit, FixOutput, PullRequest

V0 = '''"""Basic statistics helpers."""


def mean(values)
    return sum(values) / len(values)


def median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2]
'''

V1 = V0.replace("def mean(values)\n", "def mean(values):\n")

V2 = '''"""Basic statistics helpers."""


def mean(values):
    if not values:
        raise ValueError("mean() requires at least one value")
    return sum(values) / len(values)


def median(values):
    if not values:
        raise ValueError("median() requires at least one value")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
'''

TESTS = '''import pytest

from stats import mean, median


def test_mean_basic():
    assert mean([1, 2, 3]) == 2


def test_mean_empty_raises_value_error():
    with pytest.raises(ValueError):
        mean([])


def test_median_odd():
    assert median([3, 1, 2]) == 2


def test_median_even_is_average_of_middle_two():
    assert median([4, 1, 3, 2]) == 2.5
'''

DESCRIPTION = (
    "Add mean() and median() helpers. Both must raise ValueError on empty input; "
    "median of an even-length list is the average of the two middle values."
)


def spread(total: int, note: str) -> list[QuestionScore]:
    """Scripted stand-in for the LLM's per-question scores, summing to exactly `total`."""
    scores = {q.id: int(q.max_points * total / 100) for q in RUBRIC}
    left = total - sum(scores.values())
    for q in RUBRIC:
        if left and scores[q.id] < q.max_points:
            scores[q.id] += 1
            left -= 1
    return [QuestionScore(id=q.id, score=scores[q.id], justification=note) for q in RUBRIC]


class ScriptedLLM:
    """Stands in for app.llm.structured. Decides from the real tool output in the prompt."""

    def __init__(self, schema):
        self.schema = schema

    def invoke(self, messages):
        text = "\n".join(m[1] for m in messages)
        if self.schema is SafetyVerdict:
            return SafetyVerdict(safe=True)
        if self.schema is AnalysisResult:
            return AnalysisResult(summary="Adds mean() and median()", languages=["python"], has_tests=True)
        if self.schema is ExecutionDecision:
            return ExecutionDecision(should_execute=True)
        if self.schema is ReviewOutput:
            if "py_compile: FAILED" in text:
                return ReviewOutput(
                    question_scores=spread(45, "Code does not compile."),
                    comments=["stats.py has a SyntaxError (see compiler output); nothing can run."],
                )
            if "pytest: FAILED" in text:
                return ReviewOutput(
                    question_scores=spread(69, "Tests fail."),
                    comments=[
                        "mean([]) raises ZeroDivisionError instead of ValueError.",
                        "median() returns the upper-middle element for even-length input.",
                    ],
                )
            return ReviewOutput(question_scores=spread(90, "Compiles and tests pass."), comments=[])
        if self.schema is FixOutput:
            if "py_compile: FAILED" in text:
                return FixOutput(
                    summary="Add the missing colon after mean(values).",
                    edits=[FileEdit(path="stats.py", content=V1, reason="syntax error")],
                )
            if "pytest: FAILED" in text:
                return FixOutput(
                    summary="Raise ValueError on empty input; average the middle two for even-length median.",
                    edits=[
                        FileEdit(path="stats.py", content=V2, reason="failing tests"),
                        # Out-of-scope edit: apply-fix must reject it.
                        FileEdit(path="setup.py", content="# hacked\n", reason="unrelated"),
                    ],
                )
            return FixOutput(summary="nothing to fix", edits=[])
        raise AssertionError(f"unexpected schema {self.schema}")


def run(verbose: bool = True) -> dict:
    """Run the demo, restoring any global state (patched LLM, env, settings cache) afterwards."""
    modules = (safety, analysis, execution, review, fix)
    originals = {m: m.structured for m in modules}
    old_env = os.environ.get("ENABLE_TEST_EXECUTION")
    os.environ["ENABLE_TEST_EXECUTION"] = "true"  # runs this demo's own trusted code
    get_settings.cache_clear()
    for m in modules:
        setattr(m, "structured", ScriptedLLM)
    try:
        return _run(verbose)
    finally:
        for m, original in originals.items():
            setattr(m, "structured", original)
        if old_env is None:
            os.environ.pop("ENABLE_TEST_EXECUTION", None)
        else:
            os.environ["ENABLE_TEST_EXECUTION"] = old_env
        get_settings.cache_clear()


def _run(verbose: bool) -> dict:
    from app.workflow import build_graph

    setup_logging("INFO")

    pr = PullRequest(
        repo="demo/stats", number=1, title="Add mean() and median()", description=DESCRIPTION,
        diff="+ stats.py (new file)\n+ test_stats.py (new file)",
        changed_files=["stats.py", "test_stats.py"],
        files={"stats.py": V0, "test_stats.py": TESTS, "setup.py": "# unrelated\n"},
    )
    final: dict = {}
    for update in build_graph().stream({"pr": pr}, stream_mode="updates"):
        for node, out in update.items():
            final.update(out)
            if not verbose:
                continue
            if node == "compile_test":
                ex = out["execution"]
                print("   | " + ex.output.replace("\n", "\n   | ")[:500], flush=True)
    if verbose:
        print("\nFinal stats.py diff (original -> accepted):")
        print("".join(difflib.unified_diff(
            V0.splitlines(True), final["pr"].files["stats.py"].splitlines(True), "stats.py (PR)", "stats.py (fixed)",
        )))
        print(f"status={final['status']}  score_history={final['score_history']}  fix_rounds={final['iteration']}")
    return final


if __name__ == "__main__":
    sys.exit(0 if run()["status"] == "accepted" else 1)
