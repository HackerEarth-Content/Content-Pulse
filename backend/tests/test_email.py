"""The daily plan reminder. Delivery is mocked — this asserts who gets one."""

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from core.config import settings
from core.database import Session
from core.dates import today
from core.orm import DailyEntry, Member
from integrations import email
from services.entries import members_without_a_plan

NAME = "Reminder Target"
ADDR = "reminder@hackerearth.com"


@pytest_asyncio.fixture
async def target():
    async with Session() as db:
        await db.execute(delete(Member).where(Member.email == ADDR))
        await db.commit()
        m = Member(display_name=NAME, email=ADDR, role="content")
        db.add(m)
        await db.commit()
        yield m.id
        await db.execute(delete(DailyEntry).where(DailyEntry.member_id == m.id))
        await db.execute(delete(Member).where(Member.id == m.id))
        await db.commit()


async def test_only_people_without_a_plan_are_nudged(target, client, task_type):
    async with Session() as db:
        assert any(m.id == target for m in await members_without_a_plan(db, today()))

    await client.post("/api/entries/plans", json={
        "member_id": target, "entry_date": today().isoformat(),
        "items": [{"task_type_id": task_type, "notes": "n", "due_at": today().isoformat()}],
    })

    async with Session() as db:
        assert not any(m.id == target for m in await members_without_a_plan(db, today()))


async def test_a_backfilled_jira_day_does_not_count_as_planning(target):
    """Imported Jira days are synthetic — they must not silence the reminder."""
    async with Session() as db:
        db.add(DailyEntry(member_id=target, entry_date=today(), kind="plan", source="jira",
                          idempotency_key=f"jira:{target}:{today().isoformat()}"))
        await db.commit()
        assert any(m.id == target for m in await members_without_a_plan(db, today())), \
            "a Jira import is not a plan someone filed"


async def test_members_with_no_email_are_skipped(target):
    async with Session() as db:
        member = await db.get(Member, target)
        member.email = None
        await db.commit()
        assert not any(m.id == target for m in await members_without_a_plan(db, today()))


async def test_sending_is_off_by_default(monkeypatch):
    """The guard that stops a test run mailing the team."""
    calls = []
    monkeypatch.setattr(email, "_deliver", lambda *a, **k: calls.append(a))
    assert await email.send("someone@example.com", "s", "b") is False
    assert not calls


async def test_delivery_is_attempted_when_enabled(monkeypatch):
    sent = {}

    def fake(to, subject, body, html=None):
        sent.update(to=to, subject=subject, body=body, html=html)

    monkeypatch.setattr(settings, "EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "GMAIL_SMTP_USER", "bot@example.com")
    monkeypatch.setattr(settings, "GMAIL_SMTP_APP_PASSWORD", "pw")
    monkeypatch.setattr(email, "_deliver", fake)

    subject, body, html = email.plan_reminder("Ada", "http://app/my-day")
    assert await email.send("ada@example.com", subject, body, html) is True
    assert sent["to"] == "ada@example.com"
    assert "http://app/my-day" in sent["body"]
    assert "Ada" in sent["body"]


async def test_a_failed_send_never_raises(monkeypatch):
    """A broken mail server must not take the scheduler down."""
    monkeypatch.setattr(settings, "EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "GMAIL_SMTP_USER", "bot@example.com")
    monkeypatch.setattr(settings, "GMAIL_SMTP_APP_PASSWORD", "pw")

    def boom(*a, **k):
        raise OSError("smtp unreachable")

    monkeypatch.setattr(email, "_deliver", boom)
    assert await email.send("x@example.com", "s", "b") is False
