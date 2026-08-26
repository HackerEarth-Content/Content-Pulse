"""Slack Workflow Builder webhook. Token-authenticated, not cookie — this is
the one route a browser never calls."""

from __future__ import annotations

import secrets
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_session
from core.dates import today
from core.orm import DailyEntry, EntryItem, EntryItemStatusEvent, Member, TaskType
from integrations import jira, slack
from services.entries import err

router = APIRouter(prefix="/api/intake", tags=["intake"])


class IntakeItem(BaseModel):
    task_type: str = Field(alias="taskType")
    question_type: str | None = Field(default=None, alias="questionType")
    customer: str | None = None
    count: int | None = Field(default=None, gt=0)
    notes: str | None = None

    model_config = {"populate_by_name": True}


class IntakePayload(BaseModel):
    member: str
    kind: str = Field(pattern="^(plan|update)$")
    # Not named `date` — that would shadow the imported type in this namespace.
    entry_date: date | None = Field(default=None, alias="date")
    raw_text: str | None = Field(default=None, alias="rawText")
    items: list[IntakeItem] = []
    # Send a stable value and a retried webhook won't duplicate the entry.
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey")

    model_config = {"populate_by_name": True}


async def verify_token(x_intake_token: str = Header(default="")) -> None:
    if not settings.INTAKE_TOKEN:
        raise err(503, "intake_disabled", "INTAKE_TOKEN is not configured.")
    # compare_digest, not == — a plain compare leaks the token by timing.
    if not secrets.compare_digest(x_intake_token, settings.INTAKE_TOKEN):
        raise err(401, "bad_token", "Invalid or missing X-Intake-Token.")


@router.post("/slack", dependencies=[Depends(verify_token)], status_code=201)
async def intake(
    payload: IntakePayload,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    if payload.idempotency_key:
        existing = await db.scalar(
            select(DailyEntry.id).where(
                DailyEntry.idempotency_key == payload.idempotency_key
            )
        )
        if existing:
            return {"entry_id": existing, "items": 0, "duplicate": True}

    name = payload.member.strip()
    member = await db.scalar(
        select(Member).where(func.lower(func.trim(Member.display_name)) == name.lower())
    )
    # The Django app get_or_create'd here, so every typo minted a new member and
    # split that person's metrics across the duplicates. Reject instead.
    if member is None:
        raise err(
            422,
            "unknown_member",
            f"No member named {name!r}. Add them first, or fix the Slack workflow.",
        )

    entry_date = payload.entry_date or today()
    if payload.kind == "plan":
        clash = await db.scalar(
            select(DailyEntry.id).where(
                DailyEntry.member_id == member.id,
                DailyEntry.entry_date == entry_date,
                DailyEntry.kind == "plan",
            )
        )
        if clash:
            raise err(
                409,
                "plan_exists",
                "That member already has a plan for that date.",
                entry_id=clash,
            )

    entry = DailyEntry(
        member_id=member.id,
        entry_date=entry_date,
        kind=payload.kind,
        raw_text=payload.raw_text,
        source="slack",
        idempotency_key=payload.idempotency_key,
    )
    db.add(entry)
    await db.flush()

    types = {
        name.lower(): id_
        for name, id_ in await db.execute(
            select(func.lower(TaskType.name), TaskType.id)
        )
    }
    created = []
    for order, raw in enumerate(payload.items):
        task_type_id = types.get(raw.task_type.strip().lower())
        if task_type_id is None:
            raise err(
                422, "unknown_task_type", f"No task type named {raw.task_type!r}."
            )
        status = "open" if payload.kind == "plan" else "closed"
        item = EntryItem(
            entry_id=entry.id,
            task_type_id=task_type_id,
            customer=raw.customer,
            count=raw.count,
            notes=raw.notes,
            status=status,
            sort_order=order,
            jira_state="pending" if payload.kind == "plan" else "none",
        )
        db.add(item)
        await db.flush()
        db.add(
            EntryItemStatusEvent(
                entry_item_id=item.id, to_status=status, source="slack"
            )
        )
        created.append(item.id)

    await db.commit()

    # After the commit, off the request path — Jira being slow can't fail intake.
    for item_id in created:
        if payload.kind == "plan":
            background.add_task(jira.push_item, item_id)
    background.add_task(slack.post_entry, entry.id)
    return {"entry_id": entry.id, "items": len(created), "duplicate": False}
