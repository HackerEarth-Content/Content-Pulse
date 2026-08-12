from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from core.orm import STATUSES

Status = Field(default="open", pattern="^(" + "|".join(STATUSES) + ")$")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


# ── in ────────────────────────────────────────────────────────────────────────


class ItemIn(BaseModel):
    task_type_id: int
    question_type_id: int | None = None
    customer: str | None = None
    count: int | None = Field(default=None, gt=0)
    notes: str | None = None
    due_at: date | None = None
    effort_minutes: int | None = Field(default=None, ge=0)
    status: str = Status
    # Opt in, not out. Every planned item used to be pushed to Jira whether
    # anyone wanted a ticket or not, and an unwanted ticket is far more
    # annoying to undo than a wanted one is to ask for.
    create_jira: bool = False


class Scheduled(BaseModel):
    """Hold the entry back and release it later.

    `post_at` in the past publishes immediately — there is no point refusing a
    time that has already come, and a clock skew of a few seconds shouldn't be
    an error.
    """

    post_at: datetime | None = None


class PlanIn(Scheduled):
    member_id: int
    entry_date: date
    raw_text: str | None = None
    items: list[ItemIn] = []


class PlanLineIn(BaseModel):
    """One row of the update form: progress against a planned task."""

    plan_item_id: int
    status: str = Status
    count: int | None = Field(default=None, gt=0)
    notes: str = Field(min_length=1)
    due_at: date
    # Minutes spent since the last update, not a running total.
    effort_minutes: int | None = Field(default=None, ge=0)


class UpdateIn(Scheduled):
    member_id: int
    entry_date: date
    raw_text: str | None = None
    plan_lines: list[PlanLineIn] = []
    # Work that wasn't planned. Starts open by default, same as a planned item.
    extra_items: list[ItemIn] = []


class ItemPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(" + "|".join(STATUSES) + ")$")
    count: int | None = Field(default=None, gt=0)
    notes: str | None = None
    due_at: date | None = None
    # Absolute, unlike an update line — this edits one row rather than adding to it.
    effort_minutes: int | None = Field(default=None, ge=0)


# ── out ───────────────────────────────────────────────────────────────────────


class ItemOut(ORMModel):
    id: int
    plan_item_id: int | None
    task_type_id: int
    task_type: str
    question_type: str | None
    customer: str | None
    count: int | None
    notes: str | None
    due_at: date | None
    effort_minutes: int | None
    status: str
    jira_wanted: bool
    jira_issue_key: str | None
    jira_issue_url: str | None
    jira_state: str

    @classmethod
    def of(cls, it) -> ItemOut:
        return cls(
            **{k: getattr(it, k) for k in
               ("id", "plan_item_id", "task_type_id", "customer", "count", "notes",
                "due_at", "effort_minutes", "status", "jira_wanted",
                "jira_issue_key", "jira_issue_url", "jira_state")},
            task_type=it.task_type.name,
            question_type=it.question_type.name if it.question_type else None,
        )


class EntryOut(ORMModel):
    id: int
    entry_date: date
    kind: str
    status: str
    member_id: int
    member: str
    raw_text: str | None
    source: str
    updated_at: datetime
    post_at: datetime | None
    posted_at: datetime | None
    items: list[ItemOut]

    @classmethod
    def of(cls, e) -> EntryOut:
        return cls(
            **{k: getattr(e, k) for k in
               ("id", "entry_date", "kind", "status", "member_id", "raw_text",
                "source", "updated_at", "post_at", "posted_at")},
            member=e.member.display_name,
            items=[ItemOut.of(i) for i in e.items],
        )


class WorkLogRow(ORMModel):
    """One ticket, with just enough of its entry to make sense standing alone."""

    id: int
    entry_id: int
    entry_date: date
    kind: str
    member_id: int
    member: str
    task_type: str
    question_type: str | None
    customer: str | None
    count: int | None
    effort_minutes: int | None
    notes: str | None
    due_at: date | None
    status: str
    pipeline: str
    external_issue_type: str | None
    request_type: str | None
    jira_issue_key: str | None
    jira_issue_url: str | None
    jira_state: str
    plan_item_id: int | None

    @classmethod
    def of(cls, item, entry) -> WorkLogRow:
        return cls(
            **{k: getattr(item, k) for k in
               ("id", "entry_id", "customer", "count", "effort_minutes", "notes",
                "due_at", "status", "pipeline", "external_issue_type", "request_type",
                "jira_issue_key", "jira_issue_url", "jira_state", "plan_item_id")},
            entry_date=entry.entry_date, kind=entry.kind,
            member_id=entry.member_id, member=entry.member.display_name,
            task_type=item.task_type.name,
            question_type=item.question_type.name if item.question_type else None,
        )


class StatusEventOut(ORMModel):
    from_status: str | None
    to_status: str
    source: str
    note: str | None
    changed_at: datetime


class MemberOut(ORMModel):
    id: int
    display_name: str
    email: str | None
    role: str
    is_active: bool
    slack_user_id: str | None


class MemberIn(BaseModel):
    display_name: str = Field(min_length=1)
    email: str | None = None
    role: str = Field(default="content", pattern="^(content|ae|manager|admin)$")
    slack_user_id: str | None = None


class MemberPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1)
    email: str | None = None
    role: str | None = Field(default=None, pattern="^(content|ae|manager|admin)$")
    slack_user_id: str | None = None
    is_active: bool | None = None


class LookupOut(ORMModel):
    id: int
    name: str
    is_active: bool
    sort_order: int


class LookupIn(BaseModel):
    name: str = Field(min_length=1)
    sort_order: int = 0


class LookupPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None
    sort_order: int | None = None
