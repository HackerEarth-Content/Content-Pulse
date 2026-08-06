"""All tables. Schema changes go through Alembic only — nothing here ever
calls create_all()."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from fastapi_users.db import SQLAlchemyBaseOAuthAccountTable, SQLAlchemyBaseUserTable
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
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
KINDS = ("plan", "update")
SOURCES = ("web", "slack", "api", "import")
ROLES = ("content", "ae", "manager", "admin")
JIRA_STATES = ("none", "pending", "ok", "failed")


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
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid4()))

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


class Member(Timestamps, Base):
    __tablename__ = "members"
    __table_args__ = (
        _enum("role", ROLES),
        # Spelled the way Postgres echoes it back, or every autogenerate
        # proposes dropping and recreating this index for nothing.
        Index("uq_members_name_ci",
              text("lower(TRIM(BOTH FROM display_name))"), unique=True),
        Index("ix_members_active_role", "is_active", "role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str | None] = mapped_column(unique=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL")
    )
    slack_user_id: Mapped[str | None]
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
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="RESTRICT"))
    raw_text: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(default="web")
    idempotency_key: Mapped[str | None] = mapped_column(unique=True)
    slack_reply_ts: Mapped[str | None]
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


class EntryItem(Timestamps, Base):
    __tablename__ = "entry_items"
    __table_args__ = (
        _enum("status", STATUSES),
        _enum("jira_state", JIRA_STATES),
        CheckConstraint("count IS NULL OR count > 0", name="ck_count_positive"),
        CheckConstraint(
            "effort_minutes IS NULL OR effort_minutes >= 0", name="ck_effort_non_negative"
        ),
        Index("ix_items_entry", "entry_id"),
        Index("ix_items_plan_item", "plan_item_id"),
        Index("ix_items_status_due", "status", "due_at"),
        Index("ix_items_customer", "customer"),
        # The background Jira writer's work queue.
        Index(
            "ix_items_jira_retry",
            "jira_state",
            postgresql_where=text("jira_state IN ('pending', 'failed')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("daily_entries.id", ondelete="CASCADE"))
    # Set on update rows: the plan row this one reports progress on.
    plan_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("entry_items.id", ondelete="SET NULL")
    )
    task_type_id: Mapped[int] = mapped_column(ForeignKey("task_types.id"))
    question_type_id: Mapped[int | None] = mapped_column(ForeignKey("question_types.id"))
    customer: Mapped[str | None]
    count: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[date | None]
    status: Mapped[str] = mapped_column(default="open")
    sort_order: Mapped[int] = mapped_column(default=0)
    # Minutes spent. NULL means nobody logged it — distinct from 0, and every
    # average must skip it rather than treating unlogged work as instant.
    effort_minutes: Mapped[int | None]

    jira_issue_key: Mapped[str | None]
    jira_issue_url: Mapped[str | None]
    jira_state: Mapped[str] = mapped_column(default="none")
    jira_error: Mapped[str | None] = mapped_column(Text)

    entry: Mapped[DailyEntry] = relationship(
        back_populates="items", foreign_keys=[entry_id]
    )
    task_type: Mapped[TaskType] = relationship(lazy="joined")
    question_type: Mapped[QuestionType | None] = relationship(lazy="joined")


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
