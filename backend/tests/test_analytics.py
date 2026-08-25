"""Analytics correctness against a known dataset, then a shape smoke test.

The dataset: 2 planned tasks, one closed via an update, plus 1 piece of extra
work. So 3 tasks (the update's mirror row is NOT a fourth), 2 closed.
"""

import pytest

DAY = "2030-03-04"
ENDPOINTS = [
    "summary", "trend", "by-member", "by-task-type", "by-question-type",
    "by-customer", "status-flow", "cycle-time",
    "plan-adherence", "plan-daily-status", "aging", "due-risk", "throughput", "workload",
    "open-items", "data-quality", "by-area", "by-request-type", "by-pipeline",
]


@pytest.fixture
def params(member):
    return {"from": DAY, "to": DAY, "member_id": member}


async def dataset(client, member, task_type):
    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": DAY,
        "items": [
            {"task_type_id": task_type, "count": 2, "notes": "one", "customer": "Acme", "due_at": DAY},
            {"task_type_id": task_type, "count": 5, "notes": "two", "due_at": DAY},
        ],
    })).json()
    # Open can't jump straight to closed — pass through in_progress first, via
    # a direct patch rather than a second update entry, so this still files
    # exactly one update for the day.
    await client.patch(f"/api/entry-items/{plan['items'][0]['id']}", json={"status": "in_progress"})
    await client.post("/api/entries/updates", json={
        "member_id": member, "entry_date": DAY,
        "plan_lines": [{"plan_item_id": plan["items"][0]["id"], "status": "closed",
                        "notes": "done", "due_at": DAY, "effort_minutes": 30}],
        # Explicit: extra work only defaults to open since it's a normal task
        # now, but this fixture's "2 closed" scenario predates that and still
        # wants this one closed. A fresh item's initial status isn't a
        # transition, so it's exempt from the in_progress-first rule.
        "extra_items": [{"task_type_id": task_type, "count": 1, "notes": "unplanned",
                         "status": "closed", "due_at": DAY}],
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


async def test_plan_daily_status_ignores_backfilled_jira_plans(client, member, task_type):
    """A synthetic Jira-sync plan isn't someone filing a plan — same rule as
    plan_adherence, kept day-by-day here instead of collapsed into a range."""
    from core.database import Session
    from core.orm import DailyEntry

    await dataset(client, member, task_type)  # real plan + update on DAY
    other_day = "2030-03-05"
    async with Session() as db:
        db.add(DailyEntry(member_id=member, entry_date=other_day, kind="plan",
                          source="jira", idempotency_key=f"jira:{member}:{other_day}"))
        await db.commit()

    rows = (await client.get("/api/analytics/plan-daily-status",
                             params={"from": DAY, "to": other_day, "member_id": member})).json()
    by_date = {r["entry_date"]: r for r in rows}
    assert by_date[DAY]["planned"] is True
    assert by_date[DAY]["updated"] is True
    assert by_date[other_day]["planned"] is False, "a backfilled Jira day is not a filed plan"
    assert by_date[other_day]["updated"] is False


async def test_trend_is_zero_filled(client, member, task_type):
    await dataset(client, member, task_type)
    rows = (await client.get("/api/analytics/trend", params={
        "from": "2030-03-01", "to": DAY, "member_id": member})).json()
    assert [r["date"] for r in rows] == [f"2030-03-0{i}" for i in range(1, 5)]
    assert [r["tasks"] for r in rows] == [0, 0, 0, 3]


async def test_status_flow_reads_the_event_log(client, member, task_type, params):
    await dataset(client, member, task_type)
    flow = (await client.get("/api/analytics/status-flow", params=params)).json()
    # Open can't jump straight to closed any more — it's two transitions now.
    assert {"from": "open", "to": "in_progress", "count": 1} in flow
    assert {"from": "in_progress", "to": "closed", "count": 1} in flow


async def test_cycle_time_excludes_work_logged_after_the_fact(client, member, task_type, params):
    """Everything in `dataset` is opened and closed in the same breath, which is
    also how most of the real Jira tickets arrive — 72% of them since 3 Aug were
    created and resolved inside 15 minutes. Counting those reported a median of
    0.04h, so they're excluded and surfaced separately instead of quietly."""
    await dataset(client, member, task_type)
    cycle = (await client.get("/api/analytics/cycle-time", params=params)).json()

    assert cycle["filed_retroactively"] > 0
    assert cycle["closed_tasks"] == 0, "same-instant closures are not cycle time"
    assert cycle["median_hours"] is None
    assert cycle["coverage"] == 0.0


async def test_cycle_time_measures_a_real_interval(client, member, task_type, params):
    """The other half: backdate the opening event and a genuine duration appears."""
    from datetime import timedelta

    from sqlalchemy import func, select, update as sa_update

    from core.database import Session
    from core.orm import DailyEntry, EntryItem, EntryItemStatusEvent

    await dataset(client, member, task_type)
    async with Session() as db:
        ids = (await db.execute(
            select(EntryItem.id)
            .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
            .where(DailyEntry.member_id == member)
        )).scalars().all()
        first = await db.scalar(
            select(func.min(EntryItemStatusEvent.changed_at))
            .where(EntryItemStatusEvent.entry_item_id.in_(ids))
        )
        await db.execute(
            sa_update(EntryItemStatusEvent)
            .where(EntryItemStatusEvent.entry_item_id.in_(ids),
                   EntryItemStatusEvent.to_status != "closed")
            .values(changed_at=first - timedelta(hours=6))
        )
        await db.commit()

    cycle = (await client.get("/api/analytics/cycle-time", params=params)).json()
    assert cycle["closed_tasks"] >= 1
    assert cycle["median_hours"] is not None and cycle["median_hours"] >= 5.9


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


async def test_effort_breakdown_labels_are_the_real_names(client, member, task_type, params):
    """Regression: by_customer/by_member/by_task_type labels used to be the
    literal dimension name ("customer", "member", "task_type") instead of the
    actual value, so the UI showed the field name rather than who/what it was."""
    plan = await dataset(client, member, task_type)
    await client.patch(f"/api/entry-items/{plan['items'][0]['id']}", json={"effort_minutes": 60})
    b = (await client.get("/api/analytics/effort-breakdown", params=params)).json()
    assert any(row["label"] == "Acme" for row in b["by_customer"])
    assert all(row["label"] != "customer" for row in b["by_customer"])
    assert all(row["label"] != "member" for row in b["by_member"])
    assert all(row["label"] != "task_type" for row in b["by_task_type"])


async def test_assessments_split_out_of_content_requests(client, member, task_type, params):
    """Assessment work is a Request *type* inside Content Requests, so it has to
    be carved out rather than sitting as its own Jira issue type."""
    from core.database import Session
    from core.orm import EntryItem
    from sqlalchemy import select

    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": DAY,
        "items": [{"task_type_id": task_type, "effort_minutes": 60, "notes": "a", "due_at": DAY},
                  {"task_type_id": task_type, "effort_minutes": 30, "notes": "b", "due_at": DAY}],
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


async def test_effort_breakdown_folds_assessments_into_content_requests(
    client, member, task_type, params
):
    """Unlike `by_area` above (the Requests screen's own split), the "Stream"
    breakdown behind effort_breakdown feeds the per-person and overall
    Insights pages, where an assessment is just Content Requests work."""
    from core.database import Session
    from core.orm import EntryItem
    from sqlalchemy import select

    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": DAY,
        "items": [{"task_type_id": task_type, "effort_minutes": 60, "notes": "a", "due_at": DAY},
                  {"task_type_id": task_type, "effort_minutes": 30, "notes": "b", "due_at": DAY}],
    })).json()
    async with Session() as db:
        for i, rt in enumerate(("Assessment Review", "Content Issue")):
            item = await db.scalar(
                select(EntryItem).where(EntryItem.id == plan["items"][i]["id"]))
            item.pipeline, item.request_type = "content_request", rt
        await db.commit()

    b = (await client.get("/api/analytics/effort-breakdown", params=params)).json()
    by_key = {r["key"]: r for r in b["by_area"]}
    assert "content_assessment" not in by_key
    assert by_key["content_request"]["tasks"] == 2
    assert by_key["content_request"]["effort_minutes"] == 90
    assert by_key["content_request"]["label"] == "Content Requests"
