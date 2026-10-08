from typing import Literal, Optional, TypedDict, Required

from pydantic import BaseModel, Field

from app.rubric import QuestionScore


class PullRequest(BaseModel):
    repo: str
    number: int
    title: str = ""
    description: str = ""
    head_sha: str = "" # Git commit SHA of the latest commit in the PR.
    diff: str = "" 
    changed_files: list[str] = Field(default_factory=list) # changed files 
    files: dict[str, str] = Field(default_factory=dict) ## all repo files


class SafetyResult(BaseModel):
    safe: bool = True
    reasons: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    summary: str = Field(default="", description="What the PR changes, in a few sentences")
    languages: list[str] = Field(default_factory=list)
    has_tests: bool = Field(default=False, description="Whether the PR adds or touches tests")
    risk_level: Literal["low", "medium", "high"] = "low"
    issues: list[str] = Field(
        default_factory=list, description="Potential bugs, security or design problems"
    )


class ExecutionDecision(BaseModel):
    should_execute: bool = Field(description="Whether to run the compiler/test tool")
    reason: str = ""


class ExecutionResult(BaseModel):
    ran: bool = False
    passed: Optional[bool] = None
    output: str = ""  # compile_output + test_output
    compile_output: str = ""
    test_output: str = ""


class FileEdit(BaseModel):
    path: str = Field(description="Repo-relative path of the file to write")
    content: str = Field(description="The COMPLETE new content of the file")
    reason: str = Field(default="", description="Why this file changes")


class FixOutput(BaseModel):
    summary: str = Field(description="What was fixed and why, in a few sentences")
    edits: list[FileEdit] = Field(default_factory=list)


class ReviewResult(BaseModel):
    question_scores: list[QuestionScore] = Field(default_factory=list)
    comments: list[str] = Field(default_factory=list)


# typeddict -> This is a dictionary with predefined keys and expected value types.
class ReviewState(TypedDict, total=False):
    pr: Required[PullRequest]
    safety: SafetyResult
    analysis: AnalysisResult
    decision: ExecutionDecision
    execution: ExecutionResult
    review: ReviewResult
    score: float  # 0-10, computed deterministically from review.question_scores
    category_totals: dict[str, int] # q and score
    score_history: list[float]  # one entry per review, oldest first
    proposed_fix: FixOutput  # latest fix-agent output, before validation/apply
    fix_log: list[dict]  # one entry per fix round: applied / rejected files, summary
    iteration: int  # number of fix attempts made so far
    status: str  # "running" | "accepted" | "rejected_unsafe" | "max_iterations" | "human_review"
