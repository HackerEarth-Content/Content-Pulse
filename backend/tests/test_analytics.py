"""Analytics correctness against a known dataset, then a shape smoke test.

The dataset: 2 planned tasks, one closed via an update, plus 1 piece of extra
work. So 3 tasks (the update's mirror row is NOT a fourth), 2 closed.
"""

import pytest

DAY = "2030-03-04"
ENDPOINTS = [
    "summary", "trend", "by-member", "by-task-type", "by-question-type",
    "by-customer", "status-flow", "cycle-time",
    "plan-adherence", "aging", "due-risk", "throughput", "workload",
    "open-items", "data-quality", "by-area", "by-request-type", "by-pipeline",
]


@pytest.fixture
def params(member):
    return {"from": DAY, "to": DAY, "member_id": member}


async def dataset(client, member, task_type):
    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": DAY,
        "items": [
            {"task_type_id": task_type, "count": 2, "notes": "one", "customer": "Acme"},
            {"task_type_id": task_type, "count": 5, "notes": "two"},
        ],
    })).json()
    await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": DAY,
        "plan_lines": [{"plan_item_id": plan["items"][0]["id"], "status": "closed",
                        "notes": "done", "due_at": DAY}],
        "extra_items": [{"task_type_id": task_type, "count": 1, "notes": "unplanned"}],
    })
    return plan


async def test_mirror_rows_are_not_counted_twice(client, member, task_type, params):
    await dataset(client, member, task_type)
    s = (await client.get("/api/analytics/summary", params=params)).json()
    # 2 planned + 1 extra. The update row mirroring plan item 1 is the same task.
    assert s["tasks"] == 3
    assert s["closed"] == 2 and s["open"] == 1
    assert s["plans"] == 1 and s["updates"] == 1
    assert s["volume"] == 8  # 2 + 5 + 1
    assert s["completion_rate"] == round(2 / 3, 4)


async def test_plan_adherence_splits_reported_from_silent(client, member, task_type, params):
    await dataset(client, member, task_type)
    row = (await client.get("/api/analytics/plan-adherence", params=params)).json()[0]
    assert row["planned"] == 2      # extra work isn't planned
    assert row["reported"] == 1
    assert row["closed"] == 1
    assert row["no_update"] == 1    # planned, never reported on, still open


async def test_trend_is_zero_filled(client, member, task_type):
    await dataset(client, member, task_type)
    rows = (await client.get("/api/analytics/trend", params={
        "from": "2030-03-01", "to": DAY, "member_id": member})).json()
    assert [r["date"] for r in rows] == [f"2030-03-0{i}" for i in range(1, 5)]
    assert [r["tasks"] for r in rows] == [0, 0, 0, 3]


async def test_status_flow_and_cycle_time_read_the_event_log(client, member, task_type, params):
    await dataset(client, member, task_type)
    flow = (await client.get("/api/analytics/status-flow", params=params)).json()
    assert {"from": "open", "to": "closed", "count": 1} in flow

    cycle = (await client.get("/api/analytics/cycle-time", params=params)).json()
    assert cycle["closed_tasks"] == 2
    assert cycle["median_hours"] is not None


async def test_data_quality_flags_unreported_plans(client, member, task_type, params):
    await dataset(client, member, task_type)
    dq = (await client.get("/api/analytics/data-quality", params=params)).json()
    assert dq["tasks"] == 3
    assert dq["plans_with_unreported_tasks"] == 1
    assert dq["missing"]["customer"] == 2  # only the first planned task has one


async def test_open_items_reports_age_and_customer(client, member, task_type, params):
    await dataset(client, member, task_type)
    rows = (await client.get("/api/analytics/open-items", params=params)).json()
    assert len(rows) == 1 and rows[0]["notes"] == "two"
    assert rows[0]["status"] == "open" and rows[0]["age_days"] is not None


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_endpoint_responds(client, endpoint, params):
    r = await client.get(f"/api/analytics/{endpoint}", params=params)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), (dict, list))


async def test_bad_range_rejected(client):
    r = await client.get("/api/analytics/summary",
                         params={"from": "2030-02-01", "to": "2030-01-01"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_range"


async def test_areas_partition_the_work(client, member, task_type, params):
    """Every ticket lands in exactly one area — no double counting, none lost."""
    await dataset(client, member, task_type)
    total = (await client.get("/api/analytics/summary", params=params)).json()["tasks"]
    areas = (await client.get("/api/analytics/by-area", params=params)).json()
    assert sum(a["tasks"] for a in areas) == total


async def test_assessments_split_out_of_content_requests(client, member, task_type, params):
    """Assessment work is a Request *type* inside Content Requests, so it has to
    be carved out rather than sitting as its own Jira issue type."""
    from core.database import Session
    from core.orm import EntryItem
    from sqlalchemy import select

    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": DAY,
        "items": [{"task_type_id": task_type, "effort_minutes": 60},
                  {"task_type_id": task_type, "effort_minutes": 30}],
    })).json()
    async with Session() as db:
        for i, (rt) in enumerate(("Assessment Review", "Content Issue")):
            item = await db.scalar(
                select(EntryItem).where(EntryItem.id == plan["items"][i]["id"]))
            item.pipeline, item.request_type = "content_request", rt
        await db.commit()

    by_area = {a["area"]: a for a in
               (await client.get("/api/analytics/by-area", params=params)).json()}
    assert by_area["content_assessment"]["tasks"] == 1
    assert by_area["content_request"]["tasks"] == 1
    assert by_area["content_assessment"]["effort_minutes"] == 60

    # and the same split holds when filtering to one area
    only = (await client.get("/api/analytics/summary",
                             params=params | {"area": "content_assessment"})).json()
    assert only["tasks"] == 1 and only["effort_minutes"] == 60
