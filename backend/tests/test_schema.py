"""The constraints that carry real invariants — if any of these stop biting,
bad data reaches the analytics silently. Each test rolls back."""

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.exc import DBAPIError, IntegrityError

from core.database import Session
from core.orm import DailyEntry, EntryItem, Member, TaskType


@pytest_asyncio.fixture
async def db():
    async with Session() as s:
        yield s
        await s.rollback()


@pytest_asyncio.fixture
async def fixtures(db):
    member = Member(display_name="Test Member")
    task_type = TaskType(name="Test Task Type")
    db.add_all([member, task_type])
    await db.flush()
    return member, task_type


async def test_one_plan_per_member_per_day(db, fixtures):
    member, _ = fixtures
    for _ in range(2):
        db.add(DailyEntry(entry_date=date(2026, 1, 5), kind="plan", member_id=member.id))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_two_updates_per_day_allowed(db, fixtures):
    member, _ = fixtures
    for _ in range(2):
        db.add(DailyEntry(entry_date=date(2026, 1, 5), kind="update", member_id=member.id))
    await db.flush()


async def test_member_name_unique_case_insensitively(db, fixtures):
    db.add(Member(display_name="  test member  "))
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.parametrize(
    "field,value",
    [("count", 0), ("status", "done"), ("jira_state", "queued")],
)
async def test_entry_item_rejects_bad_value(db, fixtures, field, value):
    member, task_type = fixtures
    entry = DailyEntry(entry_date=date(2026, 1, 6), kind="plan", member_id=member.id)
    db.add(entry)
    await db.flush()
    db.add(EntryItem(entry_id=entry.id, task_type_id=task_type.id, **{field: value}))
    with pytest.raises((IntegrityError, DBAPIError)):
        await db.flush()
