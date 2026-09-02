"""Company-wide holidays — set by an admin, apply to everyone.

Same `integration_settings` JSONB row the personal leave list already uses
(`services.leaves`), one level up: a single date -> name map shared by the
whole team rather than one entry per member. A holiday means nobody's
expected to file a plan that day, and nothing gets posted to Slack about it.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.dates import today
from core.orm import IntegrationSetting

SETTING_KEY = "holidays"


def err(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code, {"code": code, "detail": detail})


async def _setting(db: AsyncSession) -> IntegrationSetting:
    row = await db.get(IntegrationSetting, SETTING_KEY)
    if row is None:
        row = IntegrationSetting(key=SETTING_KEY, value={})
        db.add(row)
        await db.commit()
    return row


async def list_holidays(db: AsyncSession) -> list[dict]:
    """Today onward, soonest first — past holidays aren't worth showing."""
    row = await _setting(db)
    cutoff = today().isoformat()
    return sorted(
        ({"date": d, "name": name} for d, name in row.value.items() if d >= cutoff),
        key=lambda h: h["date"],
    )


async def add_holiday(db: AsyncSession, on: date, name: str) -> None:
    if on < today():
        raise err(422, "past_date", "A holiday can only be marked from today onward.")
    row = await _setting(db)
    value = dict(row.value)
    value[on.isoformat()] = name
    row.value = value
    await db.commit()


async def remove_holiday(db: AsyncSession, on: date) -> None:
    row = await _setting(db)
    value = dict(row.value)
    value.pop(on.isoformat(), None)
    row.value = value
    await db.commit()


async def holiday_name(db: AsyncSession, on: date) -> str | None:
    """The holiday's name if `on` is one, else None — the one check every
    caller (today_status, the Slack roll call, the weekly plan post) uses."""
    row = await _setting(db)
    return row.value.get(on.isoformat())
