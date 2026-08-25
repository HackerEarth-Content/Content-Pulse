"""Plan -> update round trip and the edge cases the Django app got wrong."""

DAY = "2030-01-07"


async def plan(client, member, task_type, **over):
    body = {
        "member_id": member, "entry_date": DAY,
        "items": [{"task_type_id": task_type, "count": 2, "notes": "planned", "due_at": DAY}],
    } | over
    return await client.post("/api/entries/plans", json=body)


async def test_plan_then_update_links_and_closes(client, member, task_type):
    p = (await plan(client, member, task_type)).json()
    item_id = p["items"][0]["id"]
    assert p["items"][0]["status"] == "open"

    # Open can't jump straight to closed — it has to pass through in_progress.
    await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": DAY,
        "plan_lines": [{"plan_item_id": item_id, "status": "in_progress",
                        "notes": "starting", "due_at": DAY}],
    })
    r = await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": DAY,
        "plan_lines": [{"plan_item_id": item_id, "status": "closed",
                        "notes": "shipped", "due_at": DAY, "count": 3, "effort_minutes": 30}],
    })
    assert r.status_code == 201
    mirror = r.json()["items"][0]
    assert mirror["plan_item_id"] == item_id and mirror["status"] == "closed"

    # The plan row moved too — one task, not two.
    assert (await client.get(f"/api/entries/{p['id']}")).json()["items"][0]["status"] == "closed"

    history = (await client.get(f"/api/entry-items/{item_id}/history")).json()
    assert [h["to_status"] for h in history] == ["open", "in_progress", "closed"]


async def test_second_plan_same_day_conflicts(client, member, task_type):
    first = (await plan(client, member, task_type)).json()
    r = await plan(client, member, task_type)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "plan_exists"
    assert r.json()["detail"]["entry_id"] == first["id"]


async def test_plan_upgrades_a_jira_sync_mirror_instead_of_conflicting(client, member, task_type):
    """An externally-assigned ticket parks a source="jira" plan row before the
    person ever opens the app — that row must not block them from filing a
    real plan (the My Day 'Plan your day' UI treats it as no plan at all)."""
    from core.database import Session
    from core.orm import DailyEntry, EntryItem

    async with Session() as db:
        mirror = DailyEntry(member_id=member, entry_date=DAY, kind="plan", source="jira",
                            idempotency_key=f"jira:{member}:{DAY}")
        db.add(mirror)
        await db.flush()
        db.add(EntryItem(entry_id=mirror.id, task_type_id=task_type,
                         notes="assigned externally", due_at=DAY, jira_issue_key="TCE-1"))
        await db.commit()
        mirror_id = mirror.id

    r = await plan(client, member, task_type)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["id"] == mirror_id, "upgraded the same row, not a second one"
    assert body["source"] == "web"
    keys = {it.get("jira_issue_key") for it in body["items"]}
    notes = {it["notes"] for it in body["items"]}
    assert "TCE-1" in keys, "the externally-assigned ticket is still there"
    assert "planned" in notes, "and the plan just filed is alongside it"


async def test_plan_can_be_set_with_no_new_items_when_jira_already_assigned_one(
    client, member, task_type
):
    """A day made up entirely of externally-assigned Jira work is still a real
    day — the person must be able to set the plan (so it counts as filed on
    the Plan Board) without inventing a task just to satisfy this form."""
    from core.database import Session
    from core.orm import DailyEntry, EntryItem

    async with Session() as db:
        mirror = DailyEntry(member_id=member, entry_date=DAY, kind="plan", source="jira",
                            idempotency_key=f"jira:{member}:{DAY}")
        db.add(mirror)
        await db.flush()
        db.add(EntryItem(entry_id=mirror.id, task_type_id=task_type,
                         notes="assigned externally", due_at=DAY, jira_issue_key="TCE-2"))
        await db.commit()
        mirror_id = mirror.id

    r = await plan(client, member, task_type, items=[])
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["id"] == mirror_id, "upgraded the same row, not a second one"
    assert body["source"] == "web"
    assert {it["jira_issue_key"] for it in body["items"]} == {"TCE-2"}


async def test_update_without_plan_is_typed_404(client, member, task_type):
    r = await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": DAY,
        "plan_lines": [{"plan_item_id": 999999, "status": "closed",
                        "notes": "x", "due_at": DAY}],
    })
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_plan"


async def test_plan_line_from_another_plan_rejected(client, member, task_type):
    await plan(client, member, task_type)
    r = await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": DAY,
        "plan_lines": [{"plan_item_id": 999999, "status": "closed",
                        "notes": "x", "due_at": DAY}],
    })
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "plan_item_mismatch"


async def test_extra_work_starts_open_and_can_move(client, member, task_type):
    """Unplanned work is a normal task that just wasn't on this morning's
    list — it starts open like any other, and moves the same way."""
    r = await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": DAY,
        "extra_items": [{"task_type_id": task_type, "notes": "unplanned", "due_at": DAY}],
    })
    extra = r.json()["items"][0]
    assert extra["status"] == "open" and extra["plan_item_id"] is None

    moved = await client.patch(f"/api/entry-items/{extra['id']}", json={"status": "in_progress"})
    assert moved.status_code == 200
    assert moved.json()["status"] == "in_progress"

    # Leaving in_progress requires effort on the record.
    closed = await client.patch(f"/api/entry-items/{extra['id']}",
                                json={"status": "closed", "effort_minutes": 15})
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"


async def test_extra_work_can_raise_a_jira_ticket_too(client, member, task_type):
    """Unplanned work shares `ItemIn` with planned work, so `create_jira` must
    flow through the same way — it used to be silently dropped by the frontend
    before it ever reached this endpoint."""
    r = await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": DAY,
        "extra_items": [{"task_type_id": task_type, "notes": "unplanned", "due_at": DAY, "create_jira": True}],
    })
    extra = r.json()["items"][0]
    assert extra["jira_wanted"] is True
    assert extra["jira_state"] == "pending"


async def test_patch_plan_item_cascades_to_its_update_rows(client, member, task_type):
    p = (await plan(client, member, task_type)).json()
    item_id = p["items"][0]["id"]
    upd = (await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": DAY,
        "plan_lines": [{"plan_item_id": item_id, "status": "in_progress",
                        "notes": "wip", "due_at": DAY}],
    })).json()

    # Leaving in_progress requires effort on the record.
    await client.patch(f"/api/entry-items/{item_id}", json={"status": "blocked", "effort_minutes": 20})
    assert (await client.get(f"/api/entries/{upd['id']}")).json()["items"][0]["status"] == "blocked"


async def test_unknown_ids_and_bad_range_are_422(client, member, task_type):
    assert (await plan(client, 999999, task_type)).status_code == 422
    assert (await plan(client, member, 999999)).status_code == 422
    r = await client.get("/api/entries", params={"from": "2030-02-01", "to": "2030-01-01"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_range"


async def test_count_must_be_positive(client, member, task_type):
    r = await plan(client, member, task_type,
                   items=[{"task_type_id": task_type, "count": 0}])
    assert r.status_code == 422


async def test_search_and_filters(client, member, task_type):
    await plan(client, member, task_type,
               items=[{"task_type_id": task_type, "notes": "zqxwv marker", "due_at": DAY}])
    params = {"from": DAY, "to": DAY, "member_id": member}
    assert (await client.get("/api/entries", params=params | {"q": "zqxwv"})).json()["total"] == 1
    assert (await client.get("/api/entries", params=params | {"q": "nomatch"})).json()["total"] == 0
    assert (await client.get("/api/entries", params=params | {"kind": "plan"})).json()["total"] == 1
    assert (await client.get("/api/entries", params=params | {"kind": "update"})).json()["total"] == 0


async def test_effort_accumulates_on_the_plan_row(client, member, task_type):
    """Two updates against one planned task must total, not overwrite — and the
    task itself must still count once."""
    p = (await plan(client, member, task_type)).json()
    item_id = p["items"][0]["id"]

    for spent, status in ((120, "in_progress"), (180, "closed")):
        await client.post("/api/entries/updates", json={
            "member_id": member, "entry_date": DAY,
            "plan_lines": [{"plan_item_id": item_id, "status": status,
                            "notes": "worked", "due_at": DAY, "effort_minutes": spent}],
        })

    assert (await client.get(f"/api/entries/{p['id']}")).json()["items"][0][
        "effort_minutes"
    ] == 300

    stats = (await client.get("/api/analytics/by-member", params={
        "from": DAY, "to": DAY, "member_id": member})).json()[0]
    assert stats["effort_minutes"] == 300, "mirrors must not be summed twice"
    assert stats["tasks"] == 1


async def test_unlogged_effort_stays_null(client, member, task_type):
    p = (await plan(client, member, task_type)).json()
    assert p["items"][0]["effort_minutes"] is None

    dq = (await client.get("/api/analytics/data-quality", params={
        "from": DAY, "to": DAY, "member_id": member})).json()
    assert dq["missing"]["effort"] == 1


async def test_status_dialog_sets_effort_absolutely(client, member, task_type):
    p = (await plan(client, member, task_type)).json()
    item_id = p["items"][0]["id"]
    await client.patch(f"/api/entry-items/{item_id}", json={"effort_minutes": 90})
    await client.patch(f"/api/entry-items/{item_id}", json={"effort_minutes": 45})
    item = (await client.get(f"/api/entries/{p['id']}")).json()["items"][0]
    assert item["effort_minutes"] == 45  # a correction, not another 90


async def test_negative_effort_rejected(client, member, task_type):
    r = await plan(client, member, task_type,
                   items=[{"task_type_id": task_type, "effort_minutes": -5}])
    assert r.status_code == 422


async def test_work_log_filters_the_rows_it_returns(client, member, task_type):
    """The screen shows one row per ticket, so filtering and paging happen on
    tickets. Filtering by entry meant `status=closed` returned entries holding
    one closed ticket and still rendered their open ones."""
    p = (await plan(client, member, task_type, items=[
        {"task_type_id": task_type, "notes": "first", "due_at": DAY},
        {"task_type_id": task_type, "notes": "second", "due_at": DAY},
    ])).json()
    # Open can't jump straight to closed — pass through in_progress first.
    item_id = p["items"][0]["id"]
    await client.patch(f"/api/entry-items/{item_id}", json={"status": "in_progress"})
    await client.patch(f"/api/entry-items/{item_id}", json={"status": "closed", "effort_minutes": 10})

    params = {"from": DAY, "to": DAY, "member_id": member}
    all_rows = (await client.get("/api/work-log", params=params)).json()
    assert all_rows["total"] == 2, "one row per ticket, not per day"

    closed = (await client.get("/api/work-log", params=params | {"status": "closed"})).json()
    assert closed["total"] == 1
    assert all(r["status"] == "closed" for r in closed["items"]), \
        "every returned row must match the filter"

    # the statuses partition the set exactly
    counts = {}
    for st in ("open", "in_progress", "blocked", "closed"):
        counts[st] = (await client.get("/api/work-log", params=params | {"status": st})).json()["total"]
    assert sum(counts.values()) == all_rows["total"]


async def test_work_log_search_covers_the_jira_key(client, member, task_type):
    p = (await plan(client, member, task_type,
                    items=[{"task_type_id": task_type, "notes": "findme-zz", "due_at": DAY}])).json()
    params = {"from": DAY, "to": DAY, "member_id": member}
    assert (await client.get("/api/work-log", params=params | {"q": "findme-zz"})).json()["total"] == 1
    assert (await client.get("/api/work-log", params=params | {"q": "nope"})).json()["total"] == 0
    assert p["items"][0]["id"]


async def test_today_strip_reports_who_still_owes_an_update(client, member, task_type):
    """The strip's whole job is the gap between planning and updating, so it
    reports the people, not just a count."""
    from core.dates import today as today_ist

    on = today_ist().isoformat()
    before = (await client.get("/api/today")).json()
    assert any(m["member_id"] == member for m in before["no_plan_yet"]), \
        "a member with no plan today should be listed as yet to plan"

    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": on,
        "items": [{"task_type_id": task_type, "notes": "today", "due_at": on}],
    })).json()

    mid = (await client.get("/api/today")).json()
    assert mid["planned"] >= 1
    assert any(m["member_id"] == member for m in mid["awaiting_update"]), \
        "planned but not updated"
    assert not any(m["member_id"] == member for m in mid["no_plan_yet"])

    # Open can't jump straight to closed — pass through in_progress first.
    await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": on,
        "plan_lines": [{"plan_item_id": plan["items"][0]["id"], "status": "in_progress",
                        "notes": "starting", "due_at": on}],
    })
    await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": on,
        "plan_lines": [{"plan_item_id": plan["items"][0]["id"], "status": "closed",
                        "notes": "done", "due_at": on, "effort_minutes": 5}],
    })

    after = (await client.get("/api/today")).json()
    assert after["updated"] == mid["updated"] + 1
    assert not any(m["member_id"] == member for m in after["awaiting_update"])


async def test_today_strip_ignores_backfilled_jira_plans(client, member, task_type):
    """Synthetic day-entries from the Jira import aren't something a person
    filed, so they must not count as 'planned today'."""
    from core.database import Session
    from core.dates import today as today_ist
    from core.orm import DailyEntry
    from sqlalchemy import select

    on = today_ist()
    async with Session() as db:
        db.add(DailyEntry(member_id=member, entry_date=on, kind="plan", source="jira",
                          idempotency_key=f"jira:{member}:{on.isoformat()}"))
        await db.commit()

    t = (await client.get("/api/today")).json()
    assert not any(m["member_id"] == member for m in t["awaiting_update"]), \
        "an imported Jira day is not a plan someone filed"

    async with Session() as db:
        row = await db.scalar(select(DailyEntry).where(
            DailyEntry.idempotency_key == f"jira:{member}:{on.isoformat()}"))
        await db.delete(row)
        await db.commit()
