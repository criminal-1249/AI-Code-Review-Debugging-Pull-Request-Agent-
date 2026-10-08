"""Non-LLM nodes (compile/test, scoring, apply-fix), routing functions and terminal nodes.

LLM agents live in app/agents/.
"""
from app.config import get_settings
from app.log import log
from app.fixes import apply_fix as _apply_fix, write_applied_fixes
from app.scoring import decide_next, score_review
from app.runner import run_validation
from app.state import ReviewState


def compile_test_tool(state: ReviewState) -> dict:
    s, pr = get_settings(), state["pr"]
    result = run_validation(
        pr.files, pr.changed_files,
        timeout=s.execution_timeout_seconds, run_tests=s.enable_test_execution,
    )
    log.info("  compile/test: %s", "PASSED" if result.passed else ("FAILED" if result.ran else "skipped"))
    for line in result.output.splitlines()[:6]:
        log.debug("    %s", line)
    return {"execution": result}


def deterministic_scoring(state: ReviewState) -> dict:
    score, totals = score_review(state["review"].question_scores)
    history = [*state.get("score_history", []), score]
    log.info("  score %.1f/10  history=%s  %s", score, history, totals)
    return {
        "score": score,
        "category_totals": totals,
        "score_history": history,
    }


def apply_fix(state: ReviewState) -> dict:
    """Validate the fixer's edits and apply them to the PR's files."""
    pr, fix = state["pr"], state["proposed_fix"]
    new_pr, applied, rejected = _apply_fix(pr, fix)
    entry = {
        "round": state.get("iteration", 0) + 1,
        "summary": fix.summary,
        "applied": applied,
        "rejected": rejected,
        "score_before": state["score"],
    }
    log.info("  fix round %d: applied=%s rejected=%s", entry["round"], applied, rejected)
    workspace = get_settings().workspace_dir
    if workspace and applied:
        try:
            entry["written"] = write_applied_fixes(new_pr, applied, workspace)
            log.info("  wrote %s to %s", entry["written"], workspace)
        except (ValueError, OSError) as e:  # the in-memory fix still stands
            entry["write_error"] = str(e)
            log.warning("  could not write fixes to workspace: %s", e)
    return {
        "pr": new_pr,
        "iteration": state.get("iteration", 0) + 1,
        "fix_log": [*state.get("fix_log", []), entry],
    }


# ---- routing -------------------------------------------------------------

def route_after_safety(state: ReviewState) -> str:
    return "analysis" if state["safety"].safe else "rejected"


def route_after_decision(state: ReviewState) -> str:
    return "compile_test" if state["decision"].should_execute else "review"


def route_after_scoring(state: ReviewState) -> str:
    s = get_settings()
    nxt = decide_next(
        state["score_history"],
        state.get("iteration", 0),
        threshold=s.accept_score_threshold,
        max_iterations=s.max_fix_iterations,
        min_improvement=s.min_score_improvement,
    )
    log.info("  decision: %s", nxt)
    return nxt


def route_after_apply(state: ReviewState) -> str:
    # An empty fix would just reproduce the same review, so stop and ask a human.
    return "compile_test" if state["fix_log"][-1]["applied"] else "human_review"


def mark_accepted(state: ReviewState) -> dict:
    log.info("  FINAL STATUS: %s", "accepted")
    return {"status": "accepted"}


def mark_rejected(state: ReviewState) -> dict:
    log.info("  FINAL STATUS: %s", "rejected_unsafe")
    return {"status": "rejected_unsafe"}


def mark_max_iterations(state: ReviewState) -> dict:
    log.info("  FINAL STATUS: %s", "max_iterations")
    return {"status": "max_iterations"}


def mark_human_review(state: ReviewState) -> dict:
    log.info("  FINAL STATUS: %s", "human_review")
    return {"status": "human_review"}
