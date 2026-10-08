"""Run the review workflow locally: python -m app.cli owner/repo#123"""
import json
import sys

from app.github import GitHubError
from app.llm import LLMConfigError
from app.main import review_pr

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m app.cli owner/repo#123")
    try:
        print(json.dumps(review_pr(sys.argv[1]), indent=2))
    except (ValueError, GitHubError, LLMConfigError) as e:
        sys.exit(f"error: {e}")
