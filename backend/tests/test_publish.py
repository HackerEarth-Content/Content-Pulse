"""Opt-in Jira tickets, and holding an entry back until its scheduled time."""

from datetime import datetime, timedelta


from core.database import Session
from core.orm import DailyEntry, EntryItem
from services import publish

DAY = "2030-05-06"


async def _plan(client, member, task_type, **extra):
    body = {
        "member_id": member,
        "entry_date": DAY,
        "items": [{"task_type_id": task_type, "notes": "a", "due_at": DAY}],
        **extra,
    }
    r = await client.post("/api/entries/plans", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_a_ticket_is_not_created_unless_asked_for(client, member, task_type):
    """The old behaviour pushed every planned item to Jira. An unwanted ticket is
    far more annoying to undo than a wanted one is to ask for."""
    entry = await _plan(client, member, task_type)
    assert entry["items"][0]["jira_wanted"] is False
    assert entry["items"][0]["jira_state"] == "none", "nothing queued"


async def test_asking_for_a_ticket_attempts_one(client, member, task_type):
    """Writes are disabled in tests, so the push runs and is refused. That
    refusal is the proof it was queued at all — `push_item` resets the state to
    'none' and records why, so asserting on `jira_state` here would be asserting
    on the guard rather than on the opt-in."""
    entry = await _plan(
        client,
        member,
        task_type,
        items=[
            {
                "task_type_id": task_type,
                "notes": "a",
                "due_at": DAY,
                "create_jira": True,
            },
        ],
    )
    assert entry["items"][0]["jira_wanted"] is True
    async with Session() as db:
        item = await db.get(EntryItem, entry["items"][0]["id"])
        assert item.jira_error and "JIRA_WRITES_ENABLED" in item.jira_error


async def test_an_unwanted_item_is_never_even_attempted(client, member, task_type):
    entry = await _plan(client, member, task_type)
    async with Session() as db:
        item = await db.get(EntryItem, entry["items"][0]["id"])
        assert item.jira_error is None, "never handed to Jira, so nothing to report"


def test_mark_pending_queues_only_what_was_asked_for():
    """The opt-in decision itself, with no integration in the way."""
    wanted = EntryItem(jira_wanted=True, jira_state="none")
    unwanted = EntryItem(jira_wanted=False, jira_state="none")
    existing = EntryItem(jira_wanted=False, jira_state="ok", jira_issue_key="TCE-1")
    entry = DailyEntry(items=[wanted, unwanted, existing])

    assert publish.mark_pending(entry) == [wanted, existing]
    assert wanted.jira_state == "pending"
    assert unwanted.jira_state == "none"
    assert existing.jira_state == "ok", "already has a ticket; only its status moves"


async def test_only_the_items_that_asked_are_queued(client, member, task_type):
    entry = await _plan(
        client,
        member,
        task_type,
        items=[
            {
                "task_type_id": task_type,
                "notes": "ticket me",
                "due_at": DAY,
                "create_jira": True,
            },
            {"task_type_id": task_type, "notes": "leave me alone", "due_at": DAY},
        ],
    )
    states = {i["notes"]: i["jira_state"] for i in entry["items"]}
    assert states == {"ticket me": "pending", "leave me alone": "none"}


async def test_a_scheduled_plan_is_held_back(client, member, task_type):
    """Written at 18:00, released at 20:00 — nothing reaches Jira in between."""
    later = (datetime.now() + timedelta(hours=2)).isoformat()
    entry = await _plan(
        client,
        member,
        task_type,
        post_at=later,
        items=[
            {
                "task_type_id": task_type,
                "notes": "a",
                "due_at": DAY,
                "create_jira": True,
            },
        ],
    )
    assert entry["posted_at"] is None
    assert entry["items"][0]["jira_state"] == "none", "held, so not queued yet"


async def test_a_past_schedule_publishes_immediately(client, member, task_type):
    """A time that has already come is not an error — clock skew shouldn't 422."""
    entry = await _plan(
        client,
        member,
        task_type,
        post_at=(datetime.now() - timedelta(minutes=5)).isoformat(),
        items=[
            {
                "task_type_id": task_type,
                "notes": "a",
                "due_at": DAY,
                "create_jira": True,
            }
        ],
    )
    assert entry["items"][0]["jira_state"] == "pending"


async def test_publish_due_releases_only_what_is_due(
    client, member, task_type, monkeypatch
):
    later = datetime.now() + timedelta(hours=2)
    entry = await _plan(
        client,
        member,
        task_type,
        post_at=later.isoformat(),
        items=[
            {
                "task_type_id": task_type,
                "notes": "a",
                "due_at": DAY,
                "create_jira": True,
            },
        ],
    )

    async with Session() as db:
        assert (await publish.publish_due(db))["due"] == 0, "not due yet"
        # Now stand at a time after the scheduled slot.
        result = await publish.publish_due(db, now=later + timedelta(minutes=1))
        assert result["published"] >= 1

        row = await db.get(DailyEntry, entry["id"])
        assert row.posted_at is not None, "stamped, so it can't go out twice"
        item = await db.get(EntryItem, entry["items"][0]["id"])
        assert item.jira_error and "JIRA_WRITES_ENABLED" in item.jira_error, (
            "handed to Jira on release, and refused there rather than here"
        )


async def test_publishing_twice_is_refused_by_posted_at(client, member, task_type):
    """A restart between the push and the commit must not double-post."""
    later = datetime.now() + timedelta(hours=2)
    await _plan(client, member, task_type, post_at=later.isoformat())
    async with Session() as db:
        first = await publish.publish_due(db, now=later + timedelta(minutes=1))
        second = await publish.publish_due(db, now=later + timedelta(minutes=2))
    assert first["published"] >= 1
    assert second["due"] == 0, "already posted, so no longer due"


def test_is_held_reads_the_clock_not_the_flag():
    now = datetime(2030, 5, 6, 18, 0)
    assert publish.is_held(DailyEntry(post_at=datetime(2030, 5, 6, 20, 0)), now)
    assert not publish.is_held(DailyEntry(post_at=datetime(2030, 5, 6, 17, 0)), now)
    assert not publish.is_held(DailyEntry(post_at=None), now), "unscheduled goes now"
