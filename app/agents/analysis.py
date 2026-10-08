from app.agents.common import UNTRUSTED_NOTICE, render_pr
from app.llm import structured
from app.log import log
from app.state import AnalysisResult, ReviewState

SYSTEM = f"""You are a code analysis agent. Read the pull request and produce a factual
analysis: what it changes, the languages involved, whether tests are present, an overall
risk level, and concrete potential issues (bugs, security, design). Do not score or
approve; a later stage does that.
{UNTRUSTED_NOTICE}"""


def code_analysis_agent(state: ReviewState) -> dict:
    result = structured(AnalysisResult).invoke(
        [("system", SYSTEM), ("human", render_pr(state["pr"]))]
    )
    log.info("  analysis: risk=%s, %d issue(s)", result.risk_level, len(result.issues))
    return {"analysis": result}
