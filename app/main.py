from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.llm import LLMConfigError
from app.github import GitHubClient, GitHubError, parse_pr_ref
from app.config import get_settings
from app.log import log, setup_logging
from app.state import ReviewState
from app.workflow import build_graph

setup_logging(get_settings().log_level)

app = FastAPI(title="AI Code Review Agent")
graph = build_graph()


class ReviewRequest(BaseModel):
    pr: str  

def review_pr(ref: str) -> dict:
    repo, number = parse_pr_ref(ref)
    log.info("Reviewing %s#%s", repo, number)
    pr = GitHubClient.from_settings().fetch_pull_request(repo, number)
    log.info("Fetched: %d changed file(s), %d file(s) in snapshot, diff %d chars", len(pr.changed_files), len(pr.files), len(pr.diff))
    initial_state: ReviewState = {"pr": pr}
    result = graph.invoke(initial_state)
    review = result.get("review")
    return {
        "pr": f"{repo}#{number}",
        "status": result["status"],
        "score": result.get("score"),
        "score_history": result.get("score_history", []),
        "category_totals": result.get("category_totals"),
        "iterations": result.get("iteration", 0),
        "safety_reasons": result["safety"].reasons if not result["safety"].safe else [],
        "execution": result["execution"].output if result.get("execution") else None,
        "comments": review.comments if review else [],
        "fix_log": result.get("fix_log", []),
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/review")
def review(req: ReviewRequest) -> dict:
    try:
        return review_pr(req.pr)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except GitHubError as e:
        raise HTTPException(502, str(e))
    except LLMConfigError as e:
        raise HTTPException(503, str(e))
