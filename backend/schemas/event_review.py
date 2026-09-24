"""Event Question Review — see EVENT_QUESTION_REVIEW.md.

Column A-H fields (title, tags, ...) come from Redash on every request and are
never persisted; only the review-state fields below are ours."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

VERDICTS = Literal["no_issue_found", "fixed", "removed"]
L1_STATUSES = Literal["not_started", "in_progress", "done"]
L2_STATUSES = Literal["not_requested", "pending", "in_progress", "done"]


class MemberRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str


class QuestionRow(BaseModel):
    setter_template_id: int
    question_type: str
    problem_id: int
    title: str
    level: str
    tags: list[str]
    score: int
    description: str = ""
    company: str | None = None
    section: str | None = None
    workspace: str | None = None
    created_by: str | None = None
    added_by: str | None = None
    library_type: str | None = None
    content_created_at: str | None = None

    last_verdict: VERDICTS | None = None
    last_reviewed_at: datetime | None = None
    last_reviewed_slug: str | None = None
    issue_summary: str | None = None
    removal_reason: str | None = None
    # A `removed` row only ever appears here because Redash just returned it
    # for this event — i.e. it's still live in the library despite being
    # flagged. No separate detection needed: the flag *is* the mismatch.
    resurfaced_removed: bool = False
    stale: bool = False

    l1_assignee: MemberRef | None = None
    l1_status: L1_STATUSES = "not_started"
    l1_comments: str | None = None

    l2_assignee: MemberRef | None = None
    l2_status: L2_STATUSES = "not_requested"
    l2_comments: str | None = None


class RecentlyReviewed(BaseModel):
    setter_template_id: int
    by: str
    at: datetime


class EventReviewSummary(BaseModel):
    needs_review_count: int
    reviewed_count: int
    recently_reviewed: list[RecentlyReviewed]


class EventReviewOut(BaseModel):
    event_slug: str
    rows: list[QuestionRow]
    summary: EventReviewSummary


class SubmitIn(BaseModel):
    event_slug: str
    setter_template_ids: list[int]
    status: VERDICTS
    note: str | None = None

    @model_validator(mode="after")
    def note_required_for_issues(self) -> "SubmitIn":
        if self.status in ("fixed", "removed") and not (self.note or "").strip():
            raise ValueError(
                "A summary (fixed) or reason (removed) is required for this verdict."
            )
        return self


class AssignIn(BaseModel):
    setter_template_ids: list[int]
    member_id: int
    level: Literal["l1", "l2"]


class ClaimIn(BaseModel):
    setter_template_id: int
    level: Literal["l1", "l2"]


class L2SubmitIn(BaseModel):
    setter_template_id: int
    comment: str

    @model_validator(mode="after")
    def comment_required(self) -> "L2SubmitIn":
        if not self.comment.strip():
            raise ValueError("A comment is required to mark an L2 review done.")
        return self


class ReassignL2In(BaseModel):
    setter_template_id: int
    member_id: int


class HistoryEntry(BaseModel):
    at: datetime
    event_slug: str
    level: Literal["l1", "l2"]
    by: str
    verdict: VERDICTS | None
    note: str | None


class HistoryOut(BaseModel):
    setter_template_id: int
    entries: list[HistoryEntry]


# ── admin data import (scripts/seed_event_review.py's real-world sibling) ────

IMPORT_STATUSES = Literal[
    "uploaded", "validating", "ready_for_review", "importing", "done", "error"
]


class ImportSheetSummary(BaseModel):
    slug: str
    questions: int
    missing_columns: list[str]
    reviews: int
    conflicts: int
    events: int


class ImportConflict(BaseModel):
    slug: str
    setter_template_id: int
    title: str
    levels: list[Literal["l1", "l2"]]


class ImportSummary(BaseModel):
    dry_run: bool
    sheets: list[ImportSheetSummary]
    warnings: list[str]
    conflicts: list[ImportConflict]
    total_questions: int
    total_reviews: int
    total_conflicts: int
    total_events: int


class ImportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    status: IMPORT_STATUSES
    error: str | None = None
    preview: ImportSummary | None = None
    result: ImportSummary | None = None
