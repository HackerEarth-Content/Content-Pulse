"""Weekly plan: one action per person per week, no tickets, no Jira. New items
only Monday/Friday; status moves any day; achievements only on Friday."""

from datetime import date

import pytest

from core.database import Session
from core.orm import WeeklyPlanItem
from services import weekly_plan as svc
from tests.test_rbac import as_ada, two_members  # noqa: F401 — reused fixtures

MONDAY = date(2026, 8, 17)
TUESDAY = date(2026, 8, 18)
FRIDAY = date(2026, 8, 21)


@pytest.fixture
def as_monday(monkeypatch):
    monkeypatch.setattr(svc, "today", lambda: MONDAY)


@pytest.fixture
def as_tuesday(monkeypatch):
    monkeypatch.setattr(svc, "today", lambda: TUESDAY)


@pytest.fixture
def as_friday(monkeypatch):
    monkeypatch.setattr(svc, "today", lambda: FRIDAY)


async def test_new_item_defaults_to_yet_to_start(client, member, as_monday):
    r = await client.post("/api/weekly-plan/items", json={
        "week_start": MONDAY.isoformat(), "action": "<b>Ship the thing</b>",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "yet_to_start"
    assert body["achievement"] is None


async def test_adding_outside_monday_or_friday_is_refused(client, member, as_tuesday):
    r = await client.post("/api/weekly-plan/items", json={
        "week_start": MONDAY.isoformat(), "action": "late add",
    })
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "window_closed"


async def test_adding_on_friday_is_allowed(client, member, as_friday):
    r = await client.post("/api/weekly-plan/items", json={
        "week_start": MONDAY.isoformat(), "action": "unplanned work",
    })
    assert r.status_code == 201


async def test_status_moves_forward_any_day(client, member, as_monday):
    created = (await client.post("/api/weekly-plan/items", json={
        "week_start": MONDAY.isoformat(), "action": "a",
    })).json()

    r = await client.patch(f"/api/weekly-plan/items/{created['id']}", json={"status": "blocked"})
    assert r.status_code == 200
    assert r.json()["status"] == "blocked"


async def test_status_cannot_be_set_back_to_yet_to_start(client, member, as_monday):
    created = (await client.post("/api/weekly-plan/items", json={
        "week_start": MONDAY.isoformat(), "action": "a",
    })).json()

    r = await client.patch(f"/api/weekly-plan/items/{created['id']}", json={"status": "yet_to_start"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "bad_status"


async def test_achievement_locked_until_friday(client, member, as_monday):
    created = (await client.post("/api/weekly-plan/items", json={
        "week_start": MONDAY.isoformat(), "action": "a",
    })).json()

    r = await client.patch(f"/api/weekly-plan/items/{created['id']}", json={"achievement": "done!"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "achievements_locked"


async def test_achievement_settable_on_friday(client, member, monkeypatch):
    monkeypatch.setattr(svc, "today", lambda: MONDAY)
    created = (await client.post("/api/weekly-plan/items", json={
        "week_start": MONDAY.isoformat(), "action": "a",
    })).json()

    monkeypatch.setattr(svc, "today", lambda: FRIDAY)
    r = await client.patch(f"/api/weekly-plan/items/{created['id']}", json={"achievement": "shipped it"})
    assert r.status_code == 200
    assert r.json()["achievement"] == "shipped it"


async def test_member_cannot_edit_someone_elses_item(as_ada, as_monday):
    c, ids = as_ada
    async with Session() as db:
        item = WeeklyPlanItem(member_id=ids["RBAC Grace"], week_start=MONDAY, action="grace's item")
        db.add(item)
        await db.commit()
        item_id = item.id

    r = await c.patch(f"/api/weekly-plan/items/{item_id}", json={"status": "in_progress"})
    assert r.status_code == 404, "must not reveal or edit another member's row"


async def test_member_cannot_view_someone_elses_week(as_ada, as_monday):
    c, ids = as_ada
    r = await c.get("/api/weekly-plan", params={
        "week": MONDAY.isoformat(), "member_id": ids["RBAC Grace"],
    })
    assert r.status_code == 200
    # Silently pinned to Ada's own week, same philosophy as everywhere else —
    # not a 403 that would confirm Grace's row exists.
    assert all(i["member_id"] == ids["RBAC Ada"] for i in r.json())


async def test_completion_requires_a_lead(as_ada):
    c, _ = as_ada
    r = await c.get("/api/weekly-plan/completion", params={"week": MONDAY.isoformat()})
    assert r.status_code == 403
