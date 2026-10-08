from app.agents.common import UNTRUSTED_NOTICE, render_pr
from app.llm import structured
from app.log import log
from app.state import ExecutionDecision, ReviewState

SYSTEM = f"""You decide whether the compiler/test tool should run for this PR.
Execute when the change touches compilable or testable code (source, tests, build config).
Skip for docs-only, comments-only, or non-code changes. You only decide yes/no; you never
choose commands. The tool runs a fixed, built-in validation (Python syntax check and tests).
{UNTRUSTED_NOTICE}"""


def execution_decision(state: ReviewState) -> dict:
    analysis = state["analysis"]
    human = (
        f"Analysis summary: {analysis.summary}\nLanguages: {analysis.languages}\n"
        f"Has tests: {analysis.has_tests}\n\n{render_pr(state['pr'])}"
    )
    decision = structured(ExecutionDecision).invoke([("system", SYSTEM), ("human", human)])
    log.info("  execute code: %s (%s)", decision.should_execute, decision.reason)
    return {"decision": decision}
