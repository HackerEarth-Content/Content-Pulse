"""Jira, Slack and the intake webhook. Every outbound call is mocked — these
assert our logic, not Atlassian's uptime."""

import asyncio

import httpx
import pytest
import pytest_asyncio

from core.config import settings
from core.database import Session
from sqlalchemy import select

from core.orm import EntryItem, IntegrationSetting
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
    # Jira write paths run against a MockTransport, so they opt in deliberately.
    monkeypatch.setattr(settings, "JIRA_WRITES_ENABLED", True)
    # Slack stays off: the two Slack tests patch _call directly, and leaving the
    # guard on stops background tasks reaching slack.com during a test run.
    monkeypatch.setattr(settings, "SLACK_WRITES_ENABLED", False)


@pytest_asyncio.fixture(autouse=True)
async def cached_options():
    """Pre-seed the createmeta cache so no test depends on a live lookup."""
    async with Session() as db:
        for name in ("Content Tasks", "Content Requests"):
            key = f"jira_options:{name}"
            if await db.get(IntegrationSetting, key) is None:
                db.add(IntegrationSetting(key=key, value={
                    "task_type": {"Internal meeting": "10235", "Documentation": "10240"},
                    "question_type": {"SQL": "10247"},
                }))
        await db.commit()


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


async def test_writes_are_off_by_default(client, member, task_type, monkeypatch):
    """The guard that stops a test run minting tickets in a live project."""
    monkeypatch.setattr(settings, "JIRA_WRITES_ENABLED", False)
    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": DAY, "items": [{"task_type_id": task_type}],
    })).json()

    called = []
    monkeypatch.setattr(jira, "_client", transport(
        lambda r: called.append(r) or httpx.Response(201, json={"key": "TCE-NOPE"})))
    await jira.push_item(plan["items"][0]["id"])

    assert not called, "no HTTP request may leave the process when writes are off"
    async with Session() as db:
        item = await db.get(EntryItem, plan["items"][0]["id"])
        assert item.jira_issue_key is None
        assert item.jira_state == "none"


async def test_created_issue_carries_every_field(client, member, task_type, monkeypatch):
    """A ticket with no task type, customer or assignee is invisible to the
    reporting this app does — so assert the whole payload, not just the key."""
    from core.database import Session as S
    from core.orm import Member, QuestionType

    async with S() as db:
        m = await db.get(Member, member)
        m.jira_account_id = "acct-123"
        qt = await db.scalar(select(QuestionType).where(QuestionType.name == "SQL"))
        await db.commit()
        qt_id = qt.id

    plan = (await client.post("/api/entries/plans", json={
        "member_id": member, "entry_date": DAY,
        "items": [{"task_type_id": task_type, "question_type_id": qt_id, "count": 4,
                   "customer": "Entri", "due_at": DAY, "effort_minutes": 90}],
    })).json()

    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            sent.update(httpx.Response(200, content=request.content).json()["fields"])
            return httpx.Response(201, json={"key": "TCE-42"})
        return httpx.Response(200, json={"fields": {}})

    monkeypatch.setattr(jira, "_client", transport(handler))
    await jira.push_item(plan["items"][0]["id"])

    assert sent["customfield_10233"] == 4, "question count"
    assert sent["customfield_10526"] == 90, "effort minutes"
    assert sent["customfield_10521"] == DAY, "due at"
    assert sent["assignee"] == {"id": "acct-123"}, "must not land unassigned"
    assert sent["customfield_10235"] == [{"id": "10247"}], "question type by option id"
    assert sent["issuetype"]["name"] == "Content Tasks"


async def test_pipeline_picks_the_issue_type(monkeypatch):
    """content_request -> Content Requests, and only that type carries the
    customer field. Exercised directly: the HTTP round trip adds nothing here."""
    from types import SimpleNamespace as N

    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            sent.update(httpx.Response(200, content=request.content).json()["fields"])
            return httpx.Response(201, json={"key": "TCE-43"})
        return httpx.Response(200, json={"fields": {}})

    monkeypatch.setattr(jira, "_client", transport(handler))
    entry = N(kind="plan", entry_date="2030-07-08", source="web", raw_text=None,
              member=N(display_name="Ada", jira_account_id=None))
    item = N(task_type=N(name="Documentation"), question_type=None, customer="Entri",
             count=None, notes=None, due_at=None, effort_minutes=None,
             pipeline="content_request")

    async with Session() as db:
        await jira.create_issue(db, entry, item)

    assert sent["issuetype"]["name"] == "Content Requests"
    assert sent["customfield_10225"] == "Entri", "customer rides only on Requests"
    assert sent["customfield_10230"] == {"id": "10240"}, "task type by option id"

    sent.clear()
    item.pipeline = "content_task"
    async with Session() as db:
        await jira.create_issue(db, entry, item)
    assert sent["issuetype"]["name"] == "Content Tasks"
    assert "customfield_10225" not in sent, "Content Tasks carry no customer"


async def test_rate_limit_is_obeyed(monkeypatch):
    """429 carries Retry-After. Ignoring it gets the account throttled harder."""
    calls, waits = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) < 3:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={})
        return httpx.Response(201, json={"key": "TCE-77"})

    real_sleep = asyncio.sleep  # patching jira.asyncio patches the module itself

    async def fake_sleep(seconds):
        waits.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(jira, "_client", transport(handler))
    monkeypatch.setattr(jira.asyncio, "sleep", fake_sleep)

    from types import SimpleNamespace as N
    entry = N(kind="plan", entry_date="2030-07-08", source="web", raw_text=None,
              member=N(display_name="Ada", jira_account_id=None))
    item = N(task_type=N(name="Documentation"), question_type=None, customer=None,
             count=None, notes=None, due_at=None, effort_minutes=None,
             pipeline="content_task")
    async with Session() as db:
        key, _ = await jira.create_issue(db, entry, item)

    assert key == "TCE-77"
    assert waits == [2.0, 2.0], "must wait what Retry-After says, not a guess"


async def test_client_errors_are_not_retried(monkeypatch):
    """A 400 is our mistake; retrying just repeats it."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(400, json={"errorMessages": ["bad field"]})

    monkeypatch.setattr(jira, "_client", transport(handler))
    from types import SimpleNamespace as N
    entry = N(kind="plan", entry_date="2030-07-08", source="web", raw_text=None,
              member=N(display_name="Ada", jira_account_id=None))
    item = N(task_type=N(name="Documentation"), question_type=None, customer=None,
             count=None, notes=None, due_at=None, effort_minutes=None,
             pipeline="content_task")
    async with Session() as db:
        with pytest.raises(RuntimeError, match="bad field"):
            await jira.create_issue(db, entry, item)
    assert len(calls) == 1, "no retry on a 4xx"
