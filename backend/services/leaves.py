"""Who's off, and on which days.

One `integration_settings` row, keyed by member id — the same no-new-table
mechanism `services.skills` already uses for the skill window. A leave day is
just a date nobody should be nagged about or paged over, not a record that
needs its own history or relationships.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.dates import today
from core.orm import IntegrationSetting

SETTING_KEY = "leaves"


def err(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code, {"code": code, "detail": detail})


async def _setting(db: AsyncSession) -> IntegrationSetting:
    row = await db.get(IntegrationSetting, SETTING_KEY)
    if row is None:
        row = IntegrationSetting(key=SETTING_KEY, value={})
        db.add(row)
        await db.commit()
    return row


def _future_only(dates: list[str]) -> list[str]:
    cutoff = today().isoformat()
    return sorted(d for d in dates if d >= cutoff)


async def list_leaves(db: AsyncSession, member_id: int) -> list[str]:
    row = await _setting(db)
    return _future_only(row.value.get(str(member_id), []))


async def add_leave_dates(
    db: AsyncSession, member_id: int, dates: list[date]
) -> list[str]:
    cutoff = today()
    if any(d < cutoff for d in dates):
        raise err(422, "past_date", "Leave can only be marked from today onward.")
    if any(d.weekday() >= 5 for d in dates):
        raise err(422, "weekend", "No need to mark leave on a Saturday or Sunday.")

    row = await _setting(db)
    value = dict(row.value)
    existing = set(value.get(str(member_id), []))
    existing |= {d.isoformat() for d in dates}
    value[str(member_id)] = _future_only(list(existing))
    row.value = value
    await db.commit()
    return value[str(member_id)]


async def remove_leave_date(db: AsyncSession, member_id: int, on: date) -> list[str]:
    row = await _setting(db)
    value = dict(row.value)
    remaining = [d for d in value.get(str(member_id), []) if d != on.isoformat()]
    value[str(member_id)] = _future_only(remaining)
    row.value = value
    await db.commit()
    return value[str(member_id)]


async def member_ids_on_leave(db: AsyncSession, on: date) -> set[int]:
    """Everyone marked off for this date — for excluding them from a roll
    call or a "no plan yet" list."""
    row = await _setting(db)
    day = on.isoformat()
    return {int(member_id) for member_id, dates in row.value.items() if day in dates}
