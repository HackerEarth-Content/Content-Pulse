"""Output contract for the MCQ Reviewer LLM call — mirrors
utils.prompts.MCQ_REVIEWER_PROMPT's required JSON shape exactly. Used both as
the structured-output schema handed to the model and as the strict parse
target for whatever comes back: a response that doesn't fit this shape is
treated as a provider failure (see services/mcq_reviewer.py), never trusted
as-is."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

CHECK_STATUSES = Literal[
    "fail",
    "borderline",
    "taxonomy_not_provided",
    "tags_not_provided",
    "not_evaluated",
    "na",
]


class CheckResult(BaseModel):
    status: CHECK_STATUSES
    reason: str
    # Only present on the `complexity` check.
    setter_difficulty: str | None = None
    assessed_difficulty: str | None = None
    # Only present on the `skill_tags` check.
    tag_status: str | None = None
    provided_tags: list[str] | None = None
    suggested_tags: list[str] | None = None
    # Only present on the `duplicate_question` check.
    duplicate_of_rows: list[int] | None = None


class QuestionReview(BaseModel):
    row_number: int
    verdict: Literal["fail"]
    checks: dict[str, CheckResult]
    suggestion: str


class DistributionGroup(BaseModel):
    sample_size: int
    expected_distribution: dict[str, float]
    observed_distribution: dict[str, float]
    tolerance: str = "5 percentage points"
    status: str


class OverallResults(BaseModel):
    total: int
    passed: int
    failed: int
    pass_pct: float
    fail_pct: float
    structural_failures: int
    clear_defects: int
    borderline_failures: int
    overall_status: Literal["clean", "issues_found"] = "issues_found"


class SetSummary(BaseModel):
    overall_results: OverallResults | None = None
    most_frequent_issues: dict[str, dict] = {}
    answer_choice_distribution: dict[str, DistributionGroup] = {}
    complexity_mismatch: dict | None = None
    skill_tag_gaps: dict | None = None
    skill_tag_analysis_status: str | None = None


class MCQReviewResult(BaseModel):
    """Top-level shape the prompt requires: only these two keys."""

    model_config = ConfigDict(extra="forbid")

    question_reviews: list[QuestionReview] = []
    set_summary: SetSummary = SetSummary()


# ── job lifecycle (mirrors core.orm.McqReviewJob) ────────────────────────────


class McqReviewJobSummary(BaseModel):
    """One row in the recent-jobs list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    status: str
    created_at: datetime


class McqReviewJobDetail(McqReviewJobSummary):
    error: str | None
    result: MCQReviewResult | None
    updated_at: datetime
