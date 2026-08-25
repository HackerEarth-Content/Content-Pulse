"""Authorization. The point of these is that a member cannot read or write
another member's rows, and that the guard is applied everywhere rather than
route by route."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from core.config import settings
from core.database import Session
from core.deps import Viewer
from core.orm import DailyEntry, Member, User
from core.users import current_user
from main import app

DAY = "2030-11-12"


def viewer_of(member, email="someone@hackerearth.com"):
    return Viewer(user=User(id="x", email=email, hashed_password=""), member=member)


# ── the rule itself ──────────────────────────────────────────────────────────


def test_lead_sees_everyone():
    v = viewer_of(Member(id=7, display_name="Lead", role="manager"))
    assert v.scope_member_id is None
    assert v.scope(99) == 99          # may look at anyone
    assert v.may_write_for(99)
    assert v.writer_id(99) == 99      # may file for anyone


def test_member_is_pinned_to_themselves():
    v = viewer_of(Member(id=7, display_name="Ada", role="content"))
    assert v.scope_member_id == 7
    assert v.scope(99) == 7, "asking for someone else must be silently pinned, not 403"
    assert v.scope(None) == 7
    assert not v.may_write_for(99)
    assert v.writer_id(99) == 7, "a client sending another id must not win"


def test_unlinked_account_matches_no_rows():
    v = viewer_of(None)
    assert v.scope_member_id == -1     # never equals a real id
    assert not v.may_write_for(1)
    with pytest.raises(Exception):
        v.writer_id(None)


@pytest.mark.parametrize("role,expected", [
    ("admin", True), ("manager", True), ("content", False), ("ae", False),
])
def test_only_leads_act_for_others(role, expected):
    assert viewer_of(Member(id=1, display_name="X", role=role)).is_lead is expected


# ── over HTTP, with two real members ─────────────────────────────────────────


@pytest_asyncio.fixture
async def two_members():
    """Ada (content) and Grace (content), each with a plan on the same day."""
    async with Session() as db:
        out = {}
        for name, email in (("RBAC Ada", "ada@example.com"), ("RBAC Grace", "grace@example.com")):
            m = await db.scalar(select(Member).where(Member.display_name == name))
            if m is None:
                m = Member(display_name=name, email=email, role="content")
                db.add(m)
                await db.commit()
            m.role, m.is_active = "content", True
            await db.execute(delete(DailyEntry).where(DailyEntry.member_id == m.id))
            await db.commit()
            out[name] = m.id

        user = await db.get(User, "rbac-ada")
        if user is None:
            db.add(User(id="rbac-ada", email="ada@example.com", hashed_password="",
                        is_verified=True))
            await db.commit()
        ada = await db.get(Member, out["RBAC Ada"])
        ada.user_id = "rbac-ada"
        await db.commit()
        return out


@pytest_asyncio.fixture
async def as_ada(two_members, monkeypatch):
    """Signed in as Ada, an ordinary member — not a super-admin."""
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", "")
    async with Session() as db:
        user = await db.get(User, "rbac-ada")
    app.dependency_overrides[current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, two_members
    app.dependency_overrides.clear()


async def test_member_cannot_read_another_members_entries(as_ada, task_type):
    c, ids = as_ada
    # Grace has a plan; Ada asks for it explicitly.
    async with Session() as db:
        entry = DailyEntry(member_id=ids["RBAC Grace"], entry_date=DAY, kind="plan")
        db.add(entry)
        await db.commit()
        grace_entry = entry.id

    listed = (await c.get("/api/entries", params={
        "from": DAY, "to": DAY, "member_id": ids["RBAC Grace"]})).json()
    assert all(e["member_id"] == ids["RBAC Ada"] for e in listed["items"]), \
        "asking for Grace's id must return Ada's rows, not Grace's"

    assert (await c.get(f"/api/entries/{grace_entry}")).status_code == 404
    assert (await c.get("/api/entries/plan", params={
        "member_id": ids["RBAC Grace"], "on": DAY})).status_code == 404


async def test_member_cannot_file_work_as_someone_else(as_ada, task_type):
    c, ids = as_ada
    r = await c.post("/api/entries/plans", json={
        "member_id": ids["RBAC Grace"], "entry_date": DAY,
        "items": [{"task_type_id": task_type, "notes": "not mine to file", "due_at": DAY}],
    })
    assert r.status_code == 201
    assert r.json()["member_id"] == ids["RBAC Ada"], "must be filed as Ada regardless"


async def test_exports_honour_the_same_scope(as_ada):
    c, ids = as_ada
    r = await c.get("/api/exports/work-log.csv", params={
        "from": DAY, "to": DAY, "member_id": ids["RBAC Grace"]})
    assert r.status_code == 200
    assert "RBAC Grace" not in r.text, "an export must not be the back door"


async def test_team_aggregates_stay_visible(as_ada):
    """Members see the team's numbers — just not each other's rows."""
    c, _ = as_ada
    for endpoint in ("summary", "by-member", "by-task-type", "trend"):
        r = await c.get(f"/api/analytics/{endpoint}", params={"from": DAY, "to": DAY})
        assert r.status_code == 200, endpoint


async def test_row_level_analytics_are_scoped(as_ada, task_type):
    c, ids = as_ada
    rows = (await c.get("/api/analytics/open-items", params={
        "from": DAY, "to": DAY, "member_id": ids["RBAC Grace"]})).json()
    assert all(r["member"] != "RBAC Grace" for r in rows)


async def test_admin_routes_refuse_ordinary_members(as_ada):
    c, ids = as_ada
    assert (await c.post("/api/members", json={"display_name": "Sneaky"})).status_code == 403
    assert (await c.patch(f"/api/members/{ids['RBAC Grace']}",
                          json={"role": "admin"})).status_code == 403
    assert (await c.post("/api/meta/lookups/task-types",
                         json={"name": "Sneaky type"})).status_code == 403


async def test_ordinary_member_cannot_delete_even_their_own_ticket(as_ada, task_type):
    """Deleting a ticket cancels its Jira issue too — irreversible enough
    that it's admin-only, not just gated on owning the row."""
    c, ids = as_ada
    r = await c.post("/api/entries/plans", json={
        "member_id": ids["RBAC Ada"], "entry_date": DAY,
        "items": [{"task_type_id": task_type, "notes": "mine to delete?", "due_at": DAY}],
    })
    item_id = r.json()["items"][0]["id"]
    assert (await c.delete(f"/api/entry-items/{item_id}")).status_code == 403


async def test_superadmin_email_works_without_a_member_row(monkeypatch):
    """The bootstrap that stops a bad members table locking everyone out."""
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", "boot@hackerearth.com")
    async with Session() as db:
        user = await db.get(User, "rbac-boot")
        if user is None:
            db.add(User(id="rbac-boot", email="boot@hackerearth.com",
                        hashed_password="", is_verified=True))
            await db.commit()
            user = await db.get(User, "rbac-boot")
    app.dependency_overrides[current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        me = (await c.get("/api/users/me")).json()
        assert me["member"] is None, "no member row, deliberately"
        r = await c.post("/api/meta/lookups/task-types", json={"name": "Bootstrap check"})
        assert r.status_code in (201, 409), "super-admin must get through anyway"
    app.dependency_overrides.clear()
