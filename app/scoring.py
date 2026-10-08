# Deterministic scoring and loop-control decisions
from app.rubric import QuestionScore, category_totals, final_score_out_of_10


def score_review(scores: list[QuestionScore]) -> tuple[float, dict[str, int]]:
    # total_score = sum(all question scores); final_score = total_score / 10
    
    return final_score_out_of_10(scores), category_totals(scores)


def decide_next(
    history: list[float],
    iteration: int,
    *, #everything after * must be passed using the parameter name
    threshold: float,
    max_iterations: int,
    min_improvement: float,
) -> str:

    if history[-1] >= threshold:
        return "accepted"
    if len(history) >= 2 and history[-1] - history[-2] < min_improvement:
        return "human_review"  # not improving meaningfully (or regressing)
    if iteration >= max_iterations:
        return "max_iterations"
    return "fix"
