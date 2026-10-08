# The LLM scores each question, code does all the arithmetic
from dataclasses import dataclass
from typing import Literal, get_args

from pydantic import BaseModel, Field


QuestionId = Literal[
    "C1", "C2", "C3", "C4", "Q1", "Q2", "Q3", "S1", "S2", "S3", "T1", "T2", "T3", "M1", "M2", "M3"
]


@dataclass(frozen=True) # frozen=True protects the rubric definition.
class Question:
    id: QuestionId
    category: str
    text: str
    max_points: int


RUBRIC: tuple[Question, ...] = (
    # Correctness /30
    Question("C1", "Correctness", "Does the change implement its stated intent with correct logic?", 10),
    Question("C2", "Correctness", "Are edge cases and boundary conditions handled?", 8),
    Question("C3", "Correctness", "Are errors and failure paths handled properly?", 6),
    Question("C4", "Correctness", "Does it avoid regressions and preserve existing API contracts?", 6),
    # Code Quality /20
    Question("Q1", "Code Quality", "Is the code readable, with clear naming?", 7),
    Question("Q2", "Code Quality", "Is it well structured, without needless duplication?", 7),
    Question("Q3", "Code Quality", "Does it follow language idioms and project conventions?", 6),
    # Security /20
    Question("S1", "Security", "Is untrusted input validated/sanitized (injection, traversal, etc.)?", 8),
    Question("S2", "Security", "Are secrets, authentication and authorization handled safely?", 6),
    Question("S3", "Security", "Are dependencies, resources and unsafe APIs used safely?", 6),
    # Testing & Validation /15
    Question("T1", "Testing & Validation", "Are tests added or updated for the change?", 6),
    Question("T2", "Testing & Validation", "Do tests meaningfully cover edge cases and failures?", 5),
    Question("T3", "Testing & Validation", "Do the compile/test execution results support correctness?", 4),
    # Maintainability /15
    Question("M1", "Maintainability", "Is the change modular with low coupling?", 6),
    Question("M2", "Maintainability", "Are docs/comments adequate where logic is non-obvious?", 4),
    Question("M3", "Maintainability", "Is complexity low enough for the code to be easy to change?", 5),
)

BY_ID = {q.id: q for q in RUBRIC} # mapping questions with id
CATEGORY_MAX: dict[str, int] = {} # variable for storing max points for each category

for _q in RUBRIC:
    CATEGORY_MAX[_q.category] = CATEGORY_MAX.get(_q.category, 0) + _q.max_points

assert CATEGORY_MAX == {
    "Correctness": 30,
    "Code Quality": 20,
    "Security": 20,
    "Testing & Validation": 15,
    "Maintainability": 15,
}

# Make sure my declared question IDs and actual questions are exactly the same.
assert set(get_args(QuestionId)) == set(BY_ID)


class QuestionScore(BaseModel):
    id: QuestionId = Field(description="Rubric question id, e.g. 'C1'")
    score: int = Field(ge=0, description="Integer points awarded; must not exceed the question's max")
    justification: str = Field(description="One or two sentences citing evidence from the code")


class ReviewOutput(BaseModel):
    """What the LLM returns. It must NOT contain any totals."""

    question_scores: list[QuestionScore]
    comments: list[str] = Field(
        default_factory=list, description="Concrete, actionable issues to fix, most important first"
    )


def validate_scores(scores: list[QuestionScore]) -> None:
    """Raise ValueError unless every rubric question is scored exactly once and in range."""
    ids = [s.id for s in scores]
    dupes = {i for i in ids if ids.count(i) > 1}
    missing = set(BY_ID) - set(ids)
    if dupes or missing:
        raise ValueError(f"Review scores invalid: duplicates={sorted(dupes)} missing={sorted(missing)}")
    for s in scores:
        if s.score > BY_ID[s.id].max_points:
            raise ValueError(f"Score for {s.id} is {s.score}, above max {BY_ID[s.id].max_points}")


def category_totals(scores: list[QuestionScore]) -> dict[str, int]:
    totals = {c: 0 for c in CATEGORY_MAX}
    for s in scores:
        totals[BY_ID[s.id].category] += s.score
    return totals


def final_score_out_of_10(scores: list[QuestionScore]) -> float:
    validate_scores(scores)
    return round(sum(s.score for s in scores) / 10, 2)  # rubric total is 100 points


def rubric_prompt() -> str:
    lines = []
    for cat, mx in CATEGORY_MAX.items():
        lines.append(f"{cat} (/{mx})")
        lines += [f"  {q.id} [0-{q.max_points}] {q.text}" for q in RUBRIC if q.category == cat]
    return "\n".join(lines)
