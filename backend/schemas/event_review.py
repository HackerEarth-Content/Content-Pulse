"""Event Question Review — see EVENT_QUESTION_REVIEW.md.

Column A-H fields (title, tags, ...) come from Redash on every request and are
never persisted; only the review-state fields below are ours."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import re

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

_SLUG = re.compile(r"[A-Za-z0-9-]+")


def _check_slug(v: str | None) -> str | None:
    if v is not None and not _SLUG.fullmatch(v):
        raise ValueError("Event slug may only contain letters, digits and hyphens.")
    return v


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
    last_reviewed_by: MemberRef | None = None
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
    l2_verdict: VERDICTS | None = None


class RecentlyReviewed(BaseModel):
    setter_template_id: int
    by: str
    at: datetime


class EventReviewSummary(BaseModel):
    needs_review_count: int
    reviewed_count: int
    fully_validated_count: int = 0
    recently_reviewed: list[RecentlyReviewed]


class EventReviewOut(BaseModel):
    event_slug: str
    rows: list[QuestionRow]
    summary: EventReviewSummary


class SubmitIn(BaseModel):
    event_slug: str
    _slug_ok = field_validator("event_slug")(lambda v: _check_slug(v))
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
    # Only used to name the event and link to it in the Slack message.
    event_slug: str | None = None

    _slug_ok = field_validator("event_slug")(lambda v: _check_slug(v))


class ClaimIn(BaseModel):
    setter_template_id: int
    level: Literal["l1", "l2"]


class L2SubmitIn(BaseModel):
    """Same shape as L1's SubmitIn: a verdict, plus a comment that's only
    required when the verdict reports a problem."""

    setter_template_ids: list[int]
    verdict: VERDICTS
    comment: str | None = None

    @model_validator(mode="after")
    def comment_required_for_issues(self) -> "L2SubmitIn":
        if self.verdict in ("fixed", "removed") and not (self.comment or "").strip():
            raise ValueError(
                "A summary (fixed) or reason (removed) is required for this verdict."
            )
        return self


class ReassignL2In(BaseModel):
    setter_template_id: int
    member_id: int


class EventListItem(BaseModel):
    event_slug: str
    total: int
    l1_done: int
    fully_validated: int
    created_by: MemberRef | None = None
    synced_at: datetime


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
