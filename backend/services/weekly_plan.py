"""One planned action per person per week, with a self-reported outcome.

Deliberately its own table, not EntryItem — a weekly plan item carries no task
type, no pipeline, no Jira ticket. New rows always start `yet_to_start`; that
status is never settable again once left. Achievements only ever get written
on a Friday.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dates import today
from core.orm import Member, WeeklyPlanItem

# `yet_to_start` is a creation-only default — nothing may PATCH an item back
# to it, and nothing may PATCH an item to it in the first place.
SETTABLE_STATUSES = ("in_progress", "blocked", "completed")


def err(status_code: int, code: str, detail: str, **extra) -> HTTPException:
    return HTTPException(status_code, {"code": code, "detail": detail, **extra})


def is_friday() -> bool:
    return today().weekday() == 4


def _guard_add_window() -> None:
    # Monday (filing) or Friday (extra rows) only — see WeeklyPlan.tsx for the
    # matching client-side time-of-day narrowing within those two days.
    if today().weekday() not in (0, 4):
        raise err(
            422,
            "window_closed",
            "Weekly plan items can only be added Monday or Friday.",
        )


async def list_items(
    db: AsyncSession, member_id: int, week_start: date
) -> list[WeeklyPlanItem]:
    return list(
        await db.scalars(
            select(WeeklyPlanItem)
            .where(
                WeeklyPlanItem.member_id == member_id,
                WeeklyPlanItem.week_start == week_start,
            )
            .order_by(WeeklyPlanItem.id)
        )
    )


async def list_items_for_all(
    db: AsyncSession, week_start: date
) -> list[WeeklyPlanItem]:
    """Every active member's items for one week — a lead browsing the whole
    team rather than one person at a time. Any week, past or future: nothing
    here narrows to "the current week", that's only ever a frontend default."""
    return list(
        await db.scalars(
            select(WeeklyPlanItem)
            .join(Member, Member.id == WeeklyPlanItem.member_id)
            .where(WeeklyPlanItem.week_start == week_start, Member.is_active.is_(True))
            .order_by(Member.display_name, WeeklyPlanItem.id)
        )
    )


async def create_item(
    db: AsyncSession,
    member_id: int,
    week_start: date,
    action: str,
) -> WeeklyPlanItem:
    _guard_add_window()
    item = WeeklyPlanItem(
        member_id=member_id, week_start=week_start, action=action.strip()
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def patch_item(
    db: AsyncSession,
    item_id: int,
    member_id: int,
    *,
    status: str | None,
    achievement: str | None,
) -> WeeklyPlanItem:
    item = await db.get(WeeklyPlanItem, item_id)
    if item is None or item.member_id != member_id:
        raise err(404, "not_found", "No such item.")

    if status is not None:
        if status not in SETTABLE_STATUSES:
            raise err(
                422,
                "bad_status",
                f"Status must be one of: {', '.join(SETTABLE_STATUSES)}.",
            )
        item.status = status

    if achievement is not None:
        if not is_friday():
            raise err(
                422,
                "achievements_locked",
                "Achievements can only be recorded on Friday.",
            )
        item.achievement = achievement.strip() or None

    await db.commit()
    await db.refresh(item)
    return item


async def completion(db: AsyncSession, week_start: date) -> dict:
    """How many active members have filed at all, and how many have moved
    at least one item off `yet_to_start` or recorded an achievement — the two
    numbers the Monday/Friday 11:59pm Slack digest reports."""
    active = set(await db.scalars(select(Member.id).where(Member.is_active.is_(True))))
    filed = set(
        await db.scalars(
            select(WeeklyPlanItem.member_id)
            .where(WeeklyPlanItem.week_start == week_start)
            .distinct()
        )
    )
    updated = set(
        await db.scalars(
            select(WeeklyPlanItem.member_id)
            .where(
                WeeklyPlanItem.week_start == week_start,
                or_(
                    WeeklyPlanItem.status != "yet_to_start",
                    WeeklyPlanItem.achievement.isnot(None),
                ),
            )
            .distinct()
        )
    )
    return {
        "active": len(active),
        "filed": len(filed & active),
        "updated": len(updated & active),
    }
