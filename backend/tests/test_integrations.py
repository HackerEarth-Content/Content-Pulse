"""Jira, Slack and the intake webhook. Every outbound call is mocked — these
assert our logic, not Atlassian's uptime."""

import httpx
import pytest

from core.config import settings
from core.database import Session
from core.orm import EntryItem
from integrations import jira, slack

DAY = "2030-07-08"


def transport(handler):
    return lambda: httpx.AsyncClient(base_url="https://jira.test",
                                     transport=httpx.MockTransport(handler), timeout=5)


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setattr(settings, "JIRA_EMAIL", "bot@example.com")
    monkeypatch.setattr(settings, "JIRA_API_TOKEN", "token")
    monkeypatch.setattr(settings, "JIRA_BASE_URL", "https://jira.test")
    monkeypatch.setattr(settings, "SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(settings, "INTAKE_TOKEN", "s3cret")


# ── Jira ──────────────────────────────────────────────────────────────────────


async def test_push_item_stores_key_and_marks_ok(client, member, task_type, monkeypatch):
    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": DAY,
        "items": [{"task_type_id": task_type, "notes": "n"}],
    })).json()
    item_id = plan["items"][0]["id"]

    monkeypatch.setattr(jira, "_client", transport(
        lambda r: httpx.Response(201, json={"key": "TCE-1"})))
    await jira.push_item(item_id)

    async with Session() as db:
        item = await db.get(EntryItem, item_id)
        assert item.jira_issue_key == "TCE-1"
        assert item.jira_state == "ok" and item.jira_error is None


async def test_push_item_records_failure_without_losing_the_task(
    client, member, task_type, monkeypatch
):
    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": DAY,
        "items": [{"task_type_id": task_type}],
    })).json()
    item_id = plan["items"][0]["id"]

    monkeypatch.setattr(jira, "_client", transport(
        lambda r: httpx.Response(403, json={"errorMessages": ["no permission"]})))
    await jira.push_item(item_id)

    async with Session() as db:
        item = await db.get(EntryItem, item_id)
        assert item.jira_state == "failed" and "no permission" in item.jira_error
        assert item.id and item.task_type_id  # the task itself survived


async def test_closed_transition_steps_through_in_progress(monkeypatch):
    """The TCE workflow hides Done until the issue is In Progress."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "GET" and request.url.path.endswith("/transitions"):
            first = sum(1 for c in calls if c.endswith("/transitions") and c.startswith("GET"))
            options = [{"id": "11", "to": {"name": "In Progress"}}]
            if first > 1:  # only after we stepped through
                options.append({"id": "31", "to": {"name": "Done"}})
            return httpx.Response(200, json={"transitions": options})
        if request.method == "GET":
            return httpx.Response(200, json={"fields": {}})
        return httpx.Response(204)

    monkeypatch.setattr(jira, "_client", transport(handler))
    async with Session() as db:
        await jira.transition(db, "TCE-1", "closed")

    posts = [c for c in calls if c.startswith("POST")]
    assert len(posts) == 2  # In Progress, then Done


async def test_transition_without_a_matching_target_raises(monkeypatch):
    monkeypatch.setattr(jira, "_client", transport(
        lambda r: httpx.Response(200, json={"transitions": [{"id": "1", "to": {"name": "Parked"}}]})))
    async with Session() as db:
        with pytest.raises(RuntimeError, match="No transition"):
            await jira.transition(db, "TCE-1", "blocked")


async def test_jira_disabled_is_not_a_failure(client, member, task_type, monkeypatch):
    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": DAY,
        "items": [{"task_type_id": task_type}],
    })).json()
    monkeypatch.setattr(settings, "JIRA_API_TOKEN", "")
    await jira.push_item(plan["items"][0]["id"])

    async with Session() as db:
        assert (await db.get(EntryItem, plan["items"][0]["id"])).jira_state == "none"


# ── Slack ─────────────────────────────────────────────────────────────────────


async def test_entry_posts_once_and_is_idempotent(client, member, task_type, monkeypatch):
    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": DAY,
        "items": [{"task_type_id": task_type, "notes": "n"}],
    })).json()

    sent = []

    async def fake_call(method, payload):
        sent.append((method, payload))
        return {"ok": True, "ts": f"172000.{len(sent)}"}

    monkeypatch.setattr(slack, "_call", fake_call)
    await slack.post_entry(plan["id"])
    first = len(sent)
    await slack.post_entry(plan["id"])  # already threaded

    assert first == 2  # parent + reply
    assert len(sent) == first, "second call must not repost"


async def test_slack_failure_never_raises(client, member, task_type, monkeypatch):
    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": DAY, "items": [{"task_type_id": task_type}],
    })).json()

    async def boom(method, payload):
        raise RuntimeError("channel_not_found")

    monkeypatch.setattr(slack, "_call", boom)
    await slack.post_entry(plan["id"])  # must not propagate


def test_reply_text_renders_tasks(client):
    from types import SimpleNamespace as N
    entry = N(
        kind="update", entry_date="2030-01-01",
        member=N(display_name="Ada"), raw_text=None,
        items=[N(jira_issue_key="TCE-9", jira_issue_url="http://j/TCE-9",
                 task_type=N(name="Content review"), customer="Acme",
                 question_type=N(name="SQL"), count=3, status="in_progress",
                 notes="halfway")],
    )
    text = slack.reply_text(entry)
    assert "*Ada* — ✅ Update" in text
    assert "<http://j/TCE-9|TCE-9> · Content review · Acme · SQL · Count: 3 · In Progress" in text
    assert "_halfway_" in text


# ── intake webhook ────────────────────────────────────────────────────────────


def payload(**over):
    return {"member": "PyTest Member", "kind": "plan", "date": DAY,
            "items": [{"taskType": "Documentation", "count": 2}]} | over


async def test_intake_requires_the_token(client, member):
    assert (await client.post("/api/intake/slack", json=payload())).status_code == 401
    r = await client.post("/api/intake/slack", json=payload(),
                          headers={"X-Intake-Token": "wrong"})
    assert r.status_code == 401


async def test_intake_creates_an_entry(client, member):
    r = await client.post("/api/intake/slack", json=payload(),
                          headers={"X-Intake-Token": "s3cret"})
    assert r.status_code == 201
    assert r.json()["items"] == 1 and r.json()["duplicate"] is False


async def test_intake_rejects_an_unknown_member(client, member):
    r = await client.post("/api/intake/slack", json=payload(member="Shivendrra"),
                          headers={"X-Intake-Token": "s3cret"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_member"


async def test_intake_matches_names_case_insensitively(client, member):
    r = await client.post("/api/intake/slack", json=payload(member="  pytest member "),
                          headers={"X-Intake-Token": "s3cret"})
    assert r.status_code == 201


async def test_intake_is_idempotent_with_a_key(client, member):
    body = payload(idempotencyKey="wf-run-42")
    head = {"X-Intake-Token": "s3cret"}
    first = (await client.post("/api/intake/slack", json=body, headers=head)).json()
    second = (await client.post("/api/intake/slack", json=body, headers=head)).json()
    assert second["duplicate"] is True
    assert second["entry_id"] == first["entry_id"]


async def test_intake_rejects_an_unknown_task_type(client, member):
    r = await client.post(
        "/api/intake/slack",
        json=payload(items=[{"taskType": "Interpretive Dance"}]),
        headers={"X-Intake-Token": "s3cret"},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_task_type"
