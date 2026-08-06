"""Who may sign in at all. Scoping once inside is covered in test_rbac.py."""

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from core.config import settings
from core.database import Session
from core.orm import Member
from core.users import _claim_member, _may_sign_in

SEAT = "seat.holder@hackerearth.com"


@pytest_asyncio.fixture
async def seat():
    """An active member whose email is the sign-in key."""
    async with Session() as db:
        await db.execute(delete(Member).where(Member.email == SEAT))
        await db.commit()
        m = Member(display_name="Seat Holder", email=SEAT, role="content")
        db.add(m)
        await db.commit()
        yield m.id
        await db.execute(delete(Member).where(Member.email == SEAT))
        await db.commit()


async def test_an_active_member_may_sign_in(seat, monkeypatch):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", "")
    async with Session() as db:
        assert await _may_sign_in(db, SEAT)
        assert await _may_sign_in(db, f"  {SEAT.upper()}  "), "case and space tolerant"


async def test_a_stranger_may_not(seat, monkeypatch):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", "")
    async with Session() as db:
        assert not await _may_sign_in(db, "nobody@hackerearth.com")


async def test_deactivating_revokes_access(seat, monkeypatch):
    """Revoking is what the Admin toggle does — it must actually lock them out."""
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", "")
    async with Session() as db:
        member = await db.get(Member, seat)
        member.is_active = False
        await db.commit()
        assert not await _may_sign_in(db, SEAT)


async def test_superadmins_get_in_with_no_member_row(monkeypatch):
    """The bootstrap: env-sourced, so a bad members table can't lock everyone out."""
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", "boss@hackerearth.com, other@x.com")
    async with Session() as db:
        assert await _may_sign_in(db, "boss@hackerearth.com")
        assert await _may_sign_in(db, "  BOSS@hackerearth.com ")
        assert not await _may_sign_in(db, "notboss@hackerearth.com")


def test_superadmin_list_is_parsed_leniently(monkeypatch):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", " A@x.com , b@X.com ,, ")
    assert settings.superadmins == {"a@x.com", "b@x.com"}


async def test_claiming_promotes_a_superadmin_and_links_the_account(seat, monkeypatch, fake_user):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", SEAT)
    async with Session() as db:
        await _claim_member(db, fake_user, SEAT)
        member = await db.scalar(select(Member).where(Member.email == SEAT))
        assert member.role == "admin", "listed in env, so promoted on sign-in"
        assert member.user_id == fake_user.id
        assert member.is_active


async def test_claiming_does_not_promote_an_ordinary_member(seat, monkeypatch, fake_user):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", "")
    async with Session() as db:
        await _claim_member(db, fake_user, SEAT)
        member = await db.scalar(select(Member).where(Member.email == SEAT))
        assert member.role == "content"
        assert member.user_id == fake_user.id


@pytest.mark.parametrize("email", ["", "   ", "not-an-email"])
async def test_junk_addresses_are_refused(email, monkeypatch):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", "")
    async with Session() as db:
        assert not await _may_sign_in(db, email)
