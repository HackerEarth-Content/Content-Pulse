"""Plan -> update round trip and the edge cases the Django app got wrong."""

DAY = "2030-01-07"


async def plan(client, member, task_type, **over):
    body = {
        "member_id": member, "entry_date": DAY,
        "items": [{"task_type_id": task_type, "count": 2, "notes": "planned"}],
    } | over
    return await client.post("/api/entries/plans", json=body)


async def test_plan_then_update_links_and_closes(client, member, task_type):
    p = (await plan(client, member, task_type)).json()
    item_id = p["items"][0]["id"]
    assert p["items"][0]["status"] == "open"

    r = await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": DAY,
        "plan_lines": [{"plan_item_id": item_id, "status": "closed",
                        "notes": "shipped", "due_at": DAY, "count": 3}],
    })
    assert r.status_code == 201
    mirror = r.json()["items"][0]
    assert mirror["plan_item_id"] == item_id and mirror["status"] == "closed"

    # The plan row moved too — one task, not two.
    assert (await client.get(f"/api/entries/{p['id']}")).json()["items"][0]["status"] == "closed"

    history = (await client.get(f"/api/entry-items/{item_id}/history")).json()
    assert [h["to_status"] for h in history] == ["open", "closed"]


async def test_second_plan_same_day_conflicts(client, member, task_type):
    first = (await plan(client, member, task_type)).json()
    r = await plan(client, member, task_type)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "plan_exists"
    assert r.json()["detail"]["entry_id"] == first["id"]


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


async def test_extra_work_lands_closed_and_cannot_move(client, member, task_type):
    r = await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": DAY,
        "extra_items": [{"task_type_id": task_type, "notes": "unplanned"}],
    })
    extra = r.json()["items"][0]
    assert extra["status"] == "closed" and extra["plan_item_id"] is None

    moved = await client.patch(f"/api/entry-items/{extra['id']}", json={"status": "open"})
    assert moved.status_code == 422
    assert moved.json()["detail"]["code"] == "extra_task_immutable"


async def test_patch_plan_item_cascades_to_its_update_rows(client, member, task_type):
    p = (await plan(client, member, task_type)).json()
    item_id = p["items"][0]["id"]
    upd = (await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": DAY,
        "plan_lines": [{"plan_item_id": item_id, "status": "in_progress",
                        "notes": "wip", "due_at": DAY}],
    })).json()

    await client.patch(f"/api/entry-items/{item_id}", json={"status": "blocked"})
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
               items=[{"task_type_id": task_type, "notes": "zqxwv marker"}])
    params = {"from": DAY, "to": DAY, "member_id": member}
    assert (await client.get("/api/entries", params=params | {"q": "zqxwv"})).json()["total"] == 1
    assert (await client.get("/api/entries", params=params | {"q": "nomatch"})).json()["total"] == 0
    assert (await client.get("/api/entries", params=params | {"kind": "plan"})).json()["total"] == 1
    assert (await client.get("/api/entries", params=params | {"kind": "update"})).json()["total"] == 0
