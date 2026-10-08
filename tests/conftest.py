import pytest

from app.rubric import RUBRIC, QuestionScore, ReviewOutput
from app.state import AnalysisResult, ExecutionDecision, FileEdit, FixOutput
from app.agents.safety import SafetyVerdict


def review_with_total(total: int) -> ReviewOutput:
    """A valid review whose question scores sum to exactly `total` (0-100)."""
    left, scores = total, []
    for q in RUBRIC:
        pts = min(q.max_points, left)
        left -= pts
        scores.append(QuestionScore(id=q.id, score=pts, justification="ok"))
    assert left == 0
    return ReviewOutput(question_scores=scores, comments=["fix things"])


def full_marks(fraction: float = 1.0) -> ReviewOutput:
    return ReviewOutput(
        question_scores=[
            QuestionScore(id=q.id, score=int(q.max_points * fraction), justification="ok")
            for q in RUBRIC
        ],
        comments=["fix things"],
    )


class FakeLLM:
    """Replaces app.llm.structured: returns canned outputs keyed by schema, records prompts."""

    def __init__(self):
        self.outputs = {
            SafetyVerdict: SafetyVerdict(safe=True),
            AnalysisResult: AnalysisResult(summary="adds foo", languages=["python"], has_tests=True),
            ExecutionDecision: ExecutionDecision(should_execute=True),
            ReviewOutput: full_marks(),
            # each round adds/changes a test file so the edit always applies
            FixOutput: [
                FixOutput(summary=f"round {i}", edits=[FileEdit(path="test_gen.py", content=f"# {i}\n")])
                for i in range(1, 20)
            ],
        }
        self.calls = []

    def __call__(self, schema):
        fake = self

        class _Runnable:
            def invoke(self, messages):
                fake.calls.append((schema, messages))
                out = fake.outputs[schema]
                return out.pop(0) if isinstance(out, list) else out  # list = one per call

        return _Runnable()


@pytest.fixture(autouse=True)
def no_workspace_writes(monkeypatch):
    """Tests must never write into the real WORKSPACE_DIR from .env."""
    from app.config import get_settings

    monkeypatch.setenv("WORKSPACE_DIR", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    for mod in ("safety", "analysis", "execution", "review", "fix"):
        monkeypatch.setattr(f"app.agents.{mod}.structured", fake)
    return fake
