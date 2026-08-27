"""All tables. Schema changes go through Alembic only — nothing here ever
calls create_all()."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from fastapi_users.db import SQLAlchemyBaseOAuthAccountTable, SQLAlchemyBaseUserTable
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
    relationship,
    synonym,
)

STATUSES = ("open", "in_progress", "blocked", "closed")
# Jira owns this vocabulary — a new issue type there must not need a migration
# here, so `pipeline` is an indexed slug rather than a CHECK-constrained enum.
PIPELINES = {
    "Content Tasks": "content_task",
    "Content Requests": "content_request",
    "HC Request": "hc_request",
    "HT Request": "ht_request",
    "HC/HT Feasibility": "hc_ht_feasibility",
    "TCE: Technical writing": "technical_writing",
    "Creation and Review": "creation_and_review",
    "TCE subtask": "tce_subtask",
}
DEFAULT_PIPELINE = "content_task"


# Assessment work is a Request type, not an issue type, so the reporting areas
# don't line up 1:1 with pipelines.
ASSESSMENT_REQUEST_TYPES = {"Assessment Creation", "Assessment Review"}

AREA_LABELS = {
    "content_task": "Content Tasks",
    "content_request": "Content Requests",
    "content_assessment": "Content Assessments",
    "hc_request": "HC Request",
    "ht_request": "HT Request",
    "hc_ht_feasibility": "HC/HT Feasibility",
    "technical_writing": "Technical Writing",
    "tce_subtask": "TCE Subtask",
    "creation_and_review": "Creation and Review",
}


def area_for(pipeline: str, request_type: str | None) -> str:
    """The grouping the Requests screen reports on. Content Requests split by
    their Request type; everything else is its own area."""
    if (
        pipeline == "content_request"
        and (request_type or "") in ASSESSMENT_REQUEST_TYPES
    ):
        return "content_assessment"
    return pipeline


def pipeline_for(issue_type: str | None) -> str:
    """Unknown types get a slug rather than being dropped or mislabelled."""
    if not issue_type:
        return DEFAULT_PIPELINE
    return PIPELINES.get(
        issue_type.strip(),
        issue_type.strip()
        .lower()
        .replace(":", "")
        .replace("/", "_")
        .replace(" ", "_")
        .strip("_")
        or DEFAULT_PIPELINE,
    )


KINDS = ("plan", "update")
SOURCES = ("web", "slack", "api", "import", "jira")
ROLES = ("content", "ae", "manager", "admin")
JIRA_STATES = ("none", "pending", "ok", "failed")
# Deliberately its own vocabulary, not STATUSES — a weekly plan item is never
# "open" or "closed", it's yet to start, in progress, blocked, or completed.
WEEKLY_PLAN_STATUSES = ("yet_to_start", "in_progress", "blocked", "completed")
SKILL_CATEGORIES = ("tech", "ai", "nontech")


def _enum(col: str, values: tuple[str, ...]) -> CheckConstraint:
    joined = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{col} IN ({joined})", name=f"ck_{col}")


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[str]: ARRAY(String)}


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


# ── auth ──────────────────────────────────────────────────────────────────────


class OAuthAccount(SQLAlchemyBaseOAuthAccountTable[str], Base):
    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid4())
    )

    @declared_attr
    def user_id(cls) -> Mapped[str]:
        return mapped_column(
            Text, ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False
        )


class User(SQLAlchemyBaseUserTable[str], Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(
        "user_id", Text, primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user_id = synonym("id")
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        lazy="joined", cascade="all, delete-orphan"
    )


# ── lookups ───────────────────────────────────────────────────────────────────


class Lookup:
    """task_types / question_types / ae_metric_definitions share this shape."""

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class TaskType(Lookup, Base):
    __tablename__ = "task_types"


class QuestionType(Lookup, Base):
    __tablename__ = "question_types"


# ── members ───────────────────────────────────────────────────────────────────


class MemberAlias(Base):
    """Jira spells people differently from us — `shivendra`, `shruti.jain`,
    `Niharika Kanakala`. One row per spelling, so the backfill never guesses."""

    __tablename__ = "member_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(unique=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(default="jira")


class Member(Timestamps, Base):
    __tablename__ = "members"
    __table_args__ = (
        _enum("role", ROLES),
        # Spelled the way Postgres echoes it back, or every autogenerate
        # proposes dropping and recreating this index for nothing.
        Index(
            "uq_members_name_ci",
            text("lower(TRIM(BOTH FROM display_name))"),
            unique=True,
        ),
        Index("ix_members_active_role", "is_active", "role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str | None] = mapped_column(unique=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL")
    )
    slack_user_id: Mapped[str | None]
    # Needed to assign issues we create — without it they land unassigned and
    # attribute to nobody.
    jira_account_id: Mapped[str | None]
    role: Mapped[str] = mapped_column(default="content")
    is_active: Mapped[bool] = mapped_column(default=True)


# ── entries ───────────────────────────────────────────────────────────────────


class DailyEntry(Timestamps, Base):
    __tablename__ = "daily_entries"
    __table_args__ = (
        _enum("kind", KINDS),
        _enum("status", STATUSES),
        _enum("source", SOURCES),
        Index("ix_entries_date_kind", "entry_date", "kind"),
        Index("ix_entries_member_date", "member_id", "entry_date"),
        # One plan per member per day; updates stay unconstrained.
        Index(
            "uq_entries_one_plan",
            "member_id",
            "entry_date",
            unique=True,
            postgresql_where=text("kind = 'plan'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_date: Mapped[date]
    kind: Mapped[str]
    status: Mapped[str] = mapped_column(default="open")
    member_id: Mapped[int] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT")
    )
    raw_text: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(default="web")
    idempotency_key: Mapped[str | None] = mapped_column(unique=True)
    slack_reply_ts: Mapped[str | None]
    # Hold the entry back until this time, then push it to Jira and Slack.
    # Writing a plan at 18:00 for release at 20:00 is the point: the work is
    # captured when it's fresh, announced when the team will read it.
    post_at: Mapped[datetime | None]
    # Set once it actually went out, so a restart can't publish twice.
    posted_at: Mapped[datetime | None]
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL")
    )

    member: Mapped[Member] = relationship(lazy="joined")
    items: Mapped[list[EntryItem]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="EntryItem.sort_order",
        foreign_keys="EntryItem.entry_id",
    )


# Jira's own question-type field is a multi-select picklist — this mirrors
# that rather than forcing every item down to one, which is what silently
# dropped every second choice on the way into Jira.
entry_item_question_types = Table(
    "entry_item_question_types",
    Base.metadata,
    Column(
        "entry_item_id",
        ForeignKey("entry_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "question_type_id",
        ForeignKey("question_types.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class EntryItem(Timestamps, Base):
    __tablename__ = "entry_items"
    __table_args__ = (
        _enum("status", STATUSES),
        _enum("jira_state", JIRA_STATES),
        CheckConstraint("count IS NULL OR count > 0", name="ck_count_positive"),
        CheckConstraint(
            "effort_minutes IS NULL OR effort_minutes >= 0",
            name="ck_effort_non_negative",
        ),
        Index("ix_items_entry", "entry_id"),
        Index("ix_items_plan_item", "plan_item_id"),
        Index("ix_items_status_due", "status", "due_at"),
        Index("ix_items_customer", "customer"),
        Index("ix_items_pipeline", "pipeline"),
        # The background Jira writer's work queue.
        Index(
            "ix_items_jira_retry",
            "jira_state",
            postgresql_where=text("jira_state IN ('pending', 'failed')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("daily_entries.id", ondelete="CASCADE")
    )
    # Set on update rows: the plan row this one reports progress on.
    plan_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("entry_items.id", ondelete="SET NULL")
    )
    task_type_id: Mapped[int] = mapped_column(ForeignKey("task_types.id"))
    customer: Mapped[str | None]
    count: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[date | None]
    status: Mapped[str] = mapped_column(default="open")
    sort_order: Mapped[int] = mapped_column(default=0)
    # Minutes spent. NULL means nobody logged it — distinct from 0, and every
    # average must skip it rather than treating unlogged work as instant.
    effort_minutes: Mapped[int | None]
    # Set when the value is implausible (see the backfill's threshold). Kept, not
    # deleted — dropping it loses information, averaging it loses the truth.
    effort_suspect: Mapped[bool] = mapped_column(
        default=False, server_default=text("false")
    )
    # Which stream of work this is. The one dimension Jira has that we didn't.
    pipeline: Mapped[str] = mapped_column(
        default="content_task", server_default=text("'content_task'")
    )
    # Jira's own status and issue type verbatim, so the Requests screen can split
    # by the real type rather than by our grouping of it.
    external_status: Mapped[str | None]
    external_issue_type: Mapped[str | None]
    # Jira's "Request type" — how Content Requests sub-divide into assessment
    # work, content issues, validation and so on.
    request_type: Mapped[str | None]
    # A Content Request ticket must reference the parent issue it belongs to
    # (verified against Jira at creation time — see integrations.jira.issue_exists).
    # Optional on every other work type.
    parent_issue_key: Mapped[str | None]
    parent_issue_url: Mapped[str | None]

    # Jira's own clock. Cycle time was previously derived from our status
    # events, but an imported row only ever gets one event, so every interval
    # came out at zero and the median read 0.0h across 995 closed tasks.
    # These two are the real thing, on the 78% of issues Jira has resolved.
    external_created_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]
    resolution: Mapped[str | None]
    priority: Mapped[str | None]
    # Jira's own SLA verdict. NULL where Jira never evaluated one.
    sla_met: Mapped[bool | None]
    # Milliseconds per status name, from Jira's [CHART] Time in Status. This is
    # queue time, NOT effort — a ticket parked in TO DO accrues hours nobody
    # worked. Never sum it against effort_minutes.
    time_in_status: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Whether this task should become a Jira ticket at all. Plenty of logged
    # work has no business being a ticket, and until now every planned item was
    # pushed whether anyone wanted it or not.
    jira_wanted: Mapped[bool] = mapped_column(
        default=False, server_default=text("false")
    )
    jira_issue_key: Mapped[str | None]
    jira_issue_url: Mapped[str | None]
    jira_state: Mapped[str] = mapped_column(default="none")
    jira_error: Mapped[str | None] = mapped_column(Text)
    # True when a periodic check no longer finds this issue key in Jira — it
    # was deleted there. We never delete our own row for it: that would erase
    # history for something that was, at some point, real logged work.
    jira_missing: Mapped[bool] = mapped_column(
        default=False, server_default=text("false")
    )

    entry: Mapped[DailyEntry] = relationship(
        back_populates="items", foreign_keys=[entry_id]
    )
    task_type: Mapped[TaskType] = relationship(lazy="joined")
    question_types: Mapped[list[QuestionType]] = relationship(
        secondary=entry_item_question_types,
        lazy="selectin",
        order_by=QuestionType.sort_order,
    )


class EntryItemStatusEvent(Base):
    """Every status transition. Without this, cycle time and throughput are
    unanswerable — the old app overwrote status in place."""

    __tablename__ = "entry_item_status_events"
    __table_args__ = (Index("ix_status_events_item", "entry_item_id", "changed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_item_id: Mapped[int] = mapped_column(
        ForeignKey("entry_items.id", ondelete="CASCADE")
    )
    from_status: Mapped[str | None]
    to_status: Mapped[str]
    source: Mapped[str] = mapped_column(default="web")
    note: Mapped[str | None] = mapped_column(Text)
    changed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL")
    )
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class WeeklyPlanItem(Timestamps, Base):
    """One planned action for one person's week. Deliberately its own table —
    not an EntryItem — because a weekly plan carries no task type, no Jira
    ticket, no pipeline. It's a plan and a self-reported outcome, nothing
    else."""

    __tablename__ = "weekly_plan_items"
    __table_args__ = (
        _enum("status", WEEKLY_PLAN_STATUSES),
        Index("ix_weekly_plan_member_week", "member_id", "week_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    # The Monday of the week this item belongs to.
    week_start: Mapped[date]
    action: Mapped[str] = mapped_column(Text)
    # Filled in Friday only — null the rest of the week.
    achievement: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(default="yet_to_start")

    member: Mapped[Member] = relationship(lazy="joined")


# ── skill graph ───────────────────────────────────────────────────────────────


class Skill(Base):
    """The master skill catalogue — tech stacks, AI/agentic skills, and
    non-tech competencies people self-rate against. Seeded once from the
    team's master list; retiring one keeps every rating already on it."""

    __tablename__ = "skills"
    __table_args__ = (_enum("category", SKILL_CATEGORIES),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    category: Mapped[str]
    sub_domain: Mapped[str | None]
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class QuickLink(Timestamps, Base):
    """One saved link on one person's Quick Links tab — an OKR doc, a policy
    reference, a dashboard, whatever they keep going back to."""

    __tablename__ = "quick_links"
    __table_args__ = (Index("ix_quick_links_member", "member_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(default=0)


class MemberSkillRating(Base):
    """One person's self-rated level (L1 Awareness .. L5 Expert) on one skill.
    No row at all means "not rated" — there's no zero level to store."""

    __tablename__ = "member_skill_ratings"
    __table_args__ = (
        CheckConstraint("level BETWEEN 1 AND 5", name="ck_skill_level_range"),
        UniqueConstraint("member_id", "skill_id", name="uq_member_skill"),
        Index("ix_skill_ratings_skill", "skill_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"))
    level: Mapped[int]
    rated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    skill: Mapped[Skill] = relationship(lazy="joined")


# ── integrations ──────────────────────────────────────────────────────────────


class SlackDayThread(Base):
    __tablename__ = "slack_day_threads"
    __table_args__ = (
        UniqueConstraint("digest_date", "kind", "channel", name="uq_slack_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    digest_date: Mapped[date]
    kind: Mapped[str]
    channel: Mapped[str]
    parent_ts: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ContentRequest(Base):
    """Mirror of the Jira Content Requests board. The old app re-fetched the
    whole board on every page load and stored nothing, so no history existed."""

    __tablename__ = "content_requests"
    __table_args__ = (
        Index("ix_cr_status", "status"),
        Index("ix_cr_assignee", "assignee"),
        Index("ix_cr_created", "created_at"),
    )

    issue_key: Mapped[str] = mapped_column(primary_key=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str]
    status_category: Mapped[str | None]
    assignee: Mapped[str | None]
    reporter: Mapped[str | None]
    priority: Mapped[str | None]
    issue_type: Mapped[str | None]
    labels: Mapped[list[str]] = mapped_column(default=list)
    created_at: Mapped[datetime | None]
    updated_at: Mapped[datetime | None]
    due_date: Mapped[date | None]
    resolved_at: Mapped[datetime | None]
    url: Mapped[str]
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict)
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SyncCursor(Base):
    __tablename__ = "sync_cursors"

    key: Mapped[str] = mapped_column(primary_key=True)
    last_synced_at: Mapped[datetime | None]
    last_status: Mapped[str | None]
    last_error: Mapped[str | None] = mapped_column(Text)


class IntegrationSetting(Base):
    """Jira project key, status map, Slack channel, digest times. Secrets stay
    in env and never land here."""

    __tablename__ = "integration_settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL")
    )
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[str | None]
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
