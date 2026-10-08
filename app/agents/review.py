from app.agents.common import UNTRUSTED_NOTICE, render_pr
from app.llm import structured
from app.log import log
from app.rubric import RUBRIC, ReviewOutput, rubric_prompt, validate_scores
from app.state import ReviewResult, ReviewState

SYSTEM = f"""You are a code review agent. Score the pull request against EVERY question in the
rubric below, once each, using integer points between 0 and the question's maximum.
Justify each score with evidence. Do NOT compute category totals or an overall score;
code does that. Also list concrete, actionable comments (most important first).
If execution results show failures, reflect that in the relevant scores.

OUTPUT REQUIREMENTS
Your JSON response MUST contain BOTH top-level fields:
- "question_scores": one entry {{"id", "score", "justification"}} for EVERY rubric question id
  below (all {len(RUBRIC)} of them), each exactly once, with 0 <= score <= that question's maximum.
  Scores are required even when you also report problems; never omit them or replace them
  with comments.
- "comments": the list of actionable comment strings.
Returning only "comments" is invalid. Shape (abbreviated; yours must list every id):
{{"question_scores": [{{"id": "C1", "score": 7, "justification": "..."}}, ...],
 "comments": ["..."]}}

RUBRIC
{rubric_prompt()}

{UNTRUSTED_NOTICE}"""


def review_agent(state: ReviewState) -> dict:
    analysis, execution = state["analysis"], state.get("execution")
    exec_text = "not executed"
    if execution and execution.ran:
        exec_text = f"passed={execution.passed}\n{execution.output}"
    fixes = state.get("fix_log", [])
    fix_text = ""
    if fixes:
        fix_text = (
            "This is a re-review after automated fixes. The analysis below describes the ORIGINAL "
            "code, so its issues may already be fixed; judge the CURRENT code. Fix rounds so far:\n"
            + "\n".join(f"- round {f['round']}: {f['summary']} (files: {f['applied']})" for f in fixes)
            + "\n\n"
        )
    human = (
        f"{fix_text}Analysis: {analysis.summary}\nKnown issues: {analysis.issues}\n"
        f"Execution result: {exec_text}\n\n{render_pr(state['pr'])}"
    )
    out = structured(ReviewOutput).invoke([("system", SYSTEM), ("human", human)])
    validate_scores(out.question_scores)
    log.info("  review: %d comment(s)", len(out.comments))
    return {"review": ReviewResult(question_scores=out.question_scores, comments=out.comments)}
