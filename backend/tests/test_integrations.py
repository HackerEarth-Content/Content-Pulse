"""Jira, Slack and the intake webhook. Every outbound call is mocked — these
assert our logic, not Atlassian's uptime."""

import asyncio

import httpx
import pytest
import pytest_asyncio

from core.config import settings
from core.database import Session
from sqlalchemy import select

from core.orm import DailyEntry, EntryItem, IntegrationSetting, Member
from integrations import jira, slack
from tests.conftest import ADMIN_MEMBER, TEST_MEMBER

DAY = "2030-07-08"


def transport(handler):
    return lambda: httpx.AsyncClient(
        base_url="https://jira.test", transport=httpx.MockTransport(handler), timeout=5
    )


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
                db.add(
                    IntegrationSetting(
                        key=key,
                        value={
                            "task_type": {
                                "Internal meeting": "10235",
                                "Documentation": "10240",
                            },
                            "question_type": {"SQL": "10247"},
                        },
                    )
                )
        await db.commit()


# ── Jira ──────────────────────────────────────────────────────────────────────


async def test_push_item_stores_key_and_marks_ok(
    client, member, task_type, monkeypatch
):
    plan = (
        await client.post(
            "/api/entries/plans",
            json={
                "member_id": member,
                "entry_date": DAY,
                "items": [{"task_type_id": task_type, "notes": "n", "due_at": DAY}],
            },
        )
    ).json()
    item_id = plan["items"][0]["id"]

    monkeypatch.setattr(
        jira, "_client", transport(lambda r: httpx.Response(201, json={"key": "TCE-1"}))
    )
    await jira.push_item(item_id)

    async with Session() as db:
        item = await db.get(EntryItem, item_id)
        assert item.jira_issue_key == "TCE-1"
        assert item.jira_state == "ok" and item.jira_error is None


async def test_push_item_records_failure_without_losing_the_task(
    client, member, task_type, monkeypatch
):
    plan = (
        await client.post(
            "/api/entries/plans",
            json={
                "member_id": member,
                "entry_date": DAY,
                "items": [{"task_type_id": task_type, "notes": "n", "due_at": DAY}],
            },
        )
    ).json()
    item_id = plan["items"][0]["id"]

    monkeypatch.setattr(
        jira,
        "_client",
        transport(
            lambda r: httpx.Response(403, json={"errorMessages": ["no permission"]})
        ),
    )
    await jira.push_item(item_id)

    async with Session() as db:
        item = await db.get(EntryItem, item_id)
        assert item.jira_state == "failed" and "no permission" in item.jira_error
        assert item.id and item.task_type_id  # the task itself survived


async def test_editing_summary_after_create_updates_jiras_summary_field(
    client, member, task_type, monkeypatch
):
    """Editing the ticket's summary/task type post-creation must reach Jira's
    actual summary field, not just sit in our own notes column — a status
    change already pushed a comment, but that's not the same as the issue's
    title actually changing to match."""
    plan = (
        await client.post(
            "/api/entries/plans",
            json={
                "member_id": member,
                "entry_date": DAY,
                "items": [
                    {"task_type_id": task_type, "notes": "first draft", "due_at": DAY}
                ],
            },
        )
    ).json()
    item_id = plan["items"][0]["id"]

    async with Session() as db:
        item = await db.get(EntryItem, item_id)
        item.jira_issue_key, item.jira_issue_url = (
            "TCE-9",
            "https://jira.test/browse/TCE-9",
        )
        await db.commit()

    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            sent["fields"] = httpx.Response(200, content=request.content).json()[
                "fields"
            ]
            sent["path"] = request.url.path
            return httpx.Response(204)
        return httpx.Response(200, json={"fields": {}})

    monkeypatch.setattr(jira, "_client", transport(handler))
    await client.patch(
        f"/api/entry-items/{item_id}", json={"notes": "the real summary now"}
    )
    await asyncio.sleep(0.05)  # the sync runs as a BackgroundTask after the response

    assert sent["path"] == "/rest/api/3/issue/TCE-9"
    assert "the real summary now" in sent["fields"]["summary"]


async def test_push_fields_is_a_noop_without_a_jira_key(
    client, member, task_type, monkeypatch
):
    plan = (
        await client.post(
            "/api/entries/plans",
            json={
                "member_id": member,
                "entry_date": DAY,
                "items": [{"task_type_id": task_type, "notes": "n", "due_at": DAY}],
            },
        )
    ).json()
    item_id = plan["items"][0]["id"]

    calls = []
    monkeypatch.setattr(
        jira, "_client", transport(lambda r: calls.append(r) or httpx.Response(200))
    )
    await jira.push_fields(item_id)
    assert calls == [], "no jira_issue_key — nothing to sync"


async def test_closed_transition_steps_through_in_progress(monkeypatch):
    """The TCE workflow hides Done until the issue is In Progress."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "GET" and request.url.path.endswith("/transitions"):
            first = sum(
                1 for c in calls if c.endswith("/transitions") and c.startswith("GET")
            )
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
    monkeypatch.setattr(
        jira,
        "_client",
        transport(
            lambda r: httpx.Response(
                200, json={"transitions": [{"id": "1", "to": {"name": "Parked"}}]}
            )
        ),
    )
    async with Session() as db:
        with pytest.raises(RuntimeError, match="No transition"):
            await jira.transition(db, "TCE-1", "blocked")


async def test_jira_disabled_is_not_a_failure(client, member, task_type, monkeypatch):
    plan = (
        await client.post(
            "/api/entries/plans",
            json={
                "member_id": member,
                "entry_date": DAY,
                "items": [{"task_type_id": task_type, "notes": "n", "due_at": DAY}],
            },
        )
    ).json()
    monkeypatch.setattr(settings, "JIRA_API_TOKEN", "")
    await jira.push_item(plan["items"][0]["id"])

    async with Session() as db:
        assert (await db.get(EntryItem, plan["items"][0]["id"])).jira_state == "none"


# ── Slack ─────────────────────────────────────────────────────────────────────


async def test_entry_posts_once_and_is_idempotent(
    client, member, task_type, monkeypatch
):
    plan = (
        await client.post(
            "/api/entries/plans",
            json={
                "member_id": member,
                "entry_date": DAY,
                "items": [{"task_type_id": task_type, "notes": "n", "due_at": DAY}],
            },
        )
    ).json()

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
    plan = (
        await client.post(
            "/api/entries/plans",
            json={
                "member_id": member,
                "entry_date": DAY,
                "items": [{"task_type_id": task_type, "notes": "n", "due_at": DAY}],
            },
        )
    ).json()

    async def boom(method, payload):
        raise RuntimeError("channel_not_found")

    monkeypatch.setattr(slack, "_call", boom)
    await slack.post_entry(plan["id"])  # must not propagate


def test_reply_text_renders_tasks(client):
    from datetime import date
    from types import SimpleNamespace as N

    entry = N(
        kind="update",
        entry_date=date(2030, 1, 1),
        member=N(display_name="Ada"),
        raw_text=None,
        items=[
            N(
                jira_issue_key="TCE-9",
                jira_issue_url="http://j/TCE-9",
                task_type=N(name="Content review"),
                customer="Acme",
                question_type=N(name="SQL"),
                count=3,
                status="in_progress",
                effort_minutes=90,
                due_at=None,
                notes="halfway",
            )
        ],
    )
    text = slack.reply_text(entry)
    assert (
        "*Ada* — ✅ Update for Tuesday, 01 Jan — 1h 30m logged, 0 closed, 1 still open"
        in text
    )
    assert (
        "<http://j/TCE-9|TCE-9> · Content review · *Acme* · ⏳ In Progress · 1h 30m"
        in text
    )
    assert "_halfway_" in text


async def test_roll_call_excludes_test_fixtures_and_reports_status(
    client, task_type, monkeypatch
):
    """PyTest Member/PyTest Admin (and the RBAC fixtures) are excluded by name
    — they're test fixtures that flip is_active=True for the duration of a
    run, per tests/conftest.py, and must never get called out by name in a
    real Slack message. Two throwaway probes (cleaned up in `finally`, so a
    failed assertion still leaves the live DB clean) verify the actual
    planned/no-plan split still works for everyone else."""
    from datetime import date

    from sqlalchemy import delete

    PLANNED, NO_PLAN = "RollCall Planned Probe", "RollCall NoPlan Probe"
    async with Session() as db:
        planned_member = Member(display_name=PLANNED, is_active=True)
        db.add(planned_member)
        db.add(Member(display_name=NO_PLAN, is_active=True))
        await db.commit()
        planned_id = planned_member.id

    try:
        await client.post(
            "/api/entries/plans",
            json={
                "member_id": planned_id,
                "entry_date": DAY,
                "items": [{"task_type_id": task_type, "notes": "n", "due_at": DAY}],
            },
        )

        sent = []

        async def fake_call(method, payload):
            sent.append((method, payload))
            return {"ok": True, "ts": "172000.1"}

        monkeypatch.setattr(slack, "_call", fake_call)

        result = await slack.post_roll_call(date.fromisoformat(DAY), "morning")
        assert result == {"posted": True}
        # `_mention` also calls `_call` (users.lookupByEmail) for each active
        # member with an email — only one of these calls is the actual post.
        posts = [payload for method, payload in sent if method == "chat.postMessage"]
        assert len(posts) == 1
        text = posts[0]["text"]

        assert TEST_MEMBER not in text
        assert ADMIN_MEMBER not in text

        planned_section, _, no_plan_section = text.partition("No plan yet")
        assert "Planned" in text
        assert PLANNED in planned_section
        assert NO_PLAN in no_plan_section
    finally:
        # Entries cascade-delete their items, but the member row itself has an
        # ON DELETE RESTRICT from daily_entries — the plan filed above has to
        # go first.
        async with Session() as db:
            ids = (
                (
                    await db.execute(
                        select(Member.id).where(
                            Member.display_name.in_([PLANNED, NO_PLAN])
                        )
                    )
                )
                .scalars()
                .all()
            )
            if ids:
                await db.execute(
                    delete(DailyEntry).where(DailyEntry.member_id.in_(ids))
                )
                await db.execute(delete(Member).where(Member.id.in_(ids)))
            await db.commit()


# ── intake webhook ────────────────────────────────────────────────────────────


def payload(**over):
    return {
        "member": "PyTest Member",
        "kind": "plan",
        "date": DAY,
        "items": [{"taskType": "Documentation", "count": 2}],
    } | over


async def test_intake_requires_the_token(client, member):
    assert (await client.post("/api/intake/slack", json=payload())).status_code == 401
    r = await client.post(
        "/api/intake/slack", json=payload(), headers={"X-Intake-Token": "wrong"}
    )
    assert r.status_code == 401


async def test_intake_creates_an_entry(client, member):
    r = await client.post(
        "/api/intake/slack", json=payload(), headers={"X-Intake-Token": "s3cret"}
    )
    assert r.status_code == 201
    assert r.json()["items"] == 1 and r.json()["duplicate"] is False


async def test_intake_rejects_an_unknown_member(client, member):
    r = await client.post(
        "/api/intake/slack",
        json=payload(member="Shivendrra"),
        headers={"X-Intake-Token": "s3cret"},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_member"


async def test_intake_matches_names_case_insensitively(client, member):
    r = await client.post(
        "/api/intake/slack",
        json=payload(member="  pytest member "),
        headers={"X-Intake-Token": "s3cret"},
    )
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
    plan = (
        await client.post(
            "/api/entries/plans",
            json={
                "member_id": member,
                "entry_date": DAY,
                "items": [{"task_type_id": task_type, "notes": "n", "due_at": DAY}],
            },
        )
    ).json()

    called = []
    monkeypatch.setattr(
        jira,
        "_client",
        transport(
            lambda r: called.append(r) or httpx.Response(201, json={"key": "TCE-NOPE"})
        ),
    )
    await jira.push_item(plan["items"][0]["id"])

    assert not called, "no HTTP request may leave the process when writes are off"
    async with Session() as db:
        item = await db.get(EntryItem, plan["items"][0]["id"])
        assert item.jira_issue_key is None
        assert item.jira_state == "none"


async def test_created_issue_carries_every_field(
    client, member, task_type, monkeypatch
):
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

    plan = (
        await client.post(
            "/api/entries/plans",
            json={
                "member_id": member,
                "entry_date": DAY,
                "items": [
                    {
                        "task_type_id": task_type,
                        "question_type_ids": [qt_id],
                        "count": 4,
                        "customer": "Entri",
                        "due_at": DAY,
                        "effort_minutes": 90,
                        "notes": "n",
                    }
                ],
            },
        )
    ).json()

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


async def test_created_issue_carries_every_question_type_selected(
    client, member, task_type, monkeypatch
):
    """`question_type_ids` is a multi-select — a ticket with two selected must
    reach Jira with both, not just the first."""
    from core.database import Session as S
    from core.orm import QuestionType

    async with S() as db:
        qts = list(
            await db.scalars(
                select(QuestionType).where(
                    QuestionType.name.in_(["SQL", "Programming"])
                )
            )
        )
        # Deterministic regardless of any cache another test may have left behind.
        await db.merge(
            IntegrationSetting(
                key="jira_options:Content Tasks",
                value={
                    "task_type": {
                        "Internal meeting": "10235",
                        "Documentation": "10240",
                    },
                    "question_type": {"SQL": "10247", "Programming": "10250"},
                },
            )
        )
        await db.commit()

    plan = (
        await client.post(
            "/api/entries/plans",
            json={
                "member_id": member,
                "entry_date": DAY,
                "items": [
                    {
                        "task_type_id": task_type,
                        "question_type_ids": [qt.id for qt in qts],
                        "due_at": DAY,
                        "notes": "n",
                    }
                ],
            },
        )
    ).json()

    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            sent.update(httpx.Response(200, content=request.content).json()["fields"])
            return httpx.Response(201, json={"key": "TCE-43"})
        return httpx.Response(200, json={"fields": {}})

    monkeypatch.setattr(jira, "_client", transport(handler))
    await jira.push_item(plan["items"][0]["id"])

    assert sorted(o["id"] for o in sent["customfield_10235"]) == ["10247", "10250"]


async def test_assignee_resolved_from_email_and_cached(
    client, member, task_type, monkeypatch
):
    """No jira_account_id yet, but the member has an email — resolve it via
    Jira's user search instead of leaving the ticket unassigned, and remember
    it so the next ticket skips the lookup."""
    from core.database import Session as S
    from core.orm import Member

    async with S() as db:
        m = await db.get(Member, member)
        # The row is shared across the file's tests, so an earlier test's
        # jira_account_id would otherwise short-circuit this one.
        m.email, m.jira_account_id = "person@example.com", None
        await db.commit()

    plan = (
        await client.post(
            "/api/entries/plans",
            json={
                "member_id": member,
                "entry_date": DAY,
                "items": [{"task_type_id": task_type, "notes": "n", "due_at": DAY}],
            },
        )
    ).json()

    sent = {}
    searched = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            sent.update(httpx.Response(200, content=request.content).json()["fields"])
            return httpx.Response(201, json={"key": "TCE-51"})
        if request.url.path.endswith("/user/search"):
            searched.append(request.url.params.get("query"))
            return httpx.Response(200, json=[{"accountId": "acct-from-email"}])
        return httpx.Response(200, json={"fields": {}})

    monkeypatch.setattr(jira, "_client", transport(handler))
    await jira.push_item(plan["items"][0]["id"])

    assert searched == ["person@example.com"]
    assert sent["assignee"] == {"id": "acct-from-email"}

    async with S() as db:
        m = await db.get(Member, member)
        assert m.jira_account_id == "acct-from-email", "cached for next time"


async def test_create_issue_is_always_content_task_and_links_parent(monkeypatch):
    """Every ticket this app creates is a Content Task, regardless of
    `item.pipeline` — the app never opens a new Content Request/HC Request/etc.
    issue of its own, only a task under one that already exists. A Content
    Request item instead carries `parent_issue_key`, sent as a Jira issue
    *link* — not the `parent` field, which 400s between two same-hierarchy-
    level types like Content Tasks and Content Requests. Exercised directly:
    the HTTP round trip adds nothing here."""
    from types import SimpleNamespace as N

    sent, link = {}, {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/issue" and request.method == "POST":
            sent.update(httpx.Response(200, content=request.content).json()["fields"])
            return httpx.Response(201, json={"key": "TCE-43"})
        if request.url.path == "/rest/api/3/issueLink":
            link.update(httpx.Response(200, content=request.content).json())
            return httpx.Response(201, json={})
        return httpx.Response(200, json={"fields": {}})

    monkeypatch.setattr(jira, "_client", transport(handler))

    # Stubbed rather than seeded through `cached_options`: this shared dev DB
    # already has a real "Content Tasks" cache with its own option ids, and
    # writing a placeholder over it would corrupt that row for every test
    # that runs after this one.
    async def fake_option_ids(db, c, cfg, issue_type):
        return {"task_type": {"Documentation": "10240"}, "question_type": {}}

    monkeypatch.setattr(jira, "option_ids", fake_option_ids)
    entry = N(
        kind="plan",
        entry_date="2030-07-08",
        source="web",
        raw_text=None,
        member=N(display_name="Ada", jira_account_id=None),
    )
    item = N(
        task_type=N(name="Documentation"),
        question_types=[],
        customer="Entri",
        count=None,
        notes=None,
        due_at=None,
        effort_minutes=None,
        pipeline="content_request",
        parent_issue_key="TCE-1",
    )

    async with Session() as db:
        await jira.create_issue(db, entry, item)

    assert sent["issuetype"]["name"] == "Content Tasks"
    assert "parent" not in sent, (
        "parent field 400s between same-level types, never send it"
    )
    assert link == {
        "type": {"name": "Relates"},
        "inwardIssue": {"key": "TCE-43"},
        "outwardIssue": {"key": "TCE-1"},
    }
    assert "customfield_10225" not in sent, "Content Tasks carry no customer field"
    assert sent["customfield_10230"] == {"id": "10240"}, "task type by option id"

    sent.clear()
    link.clear()
    item.pipeline, item.parent_issue_key = "content_task", None
    async with Session() as db:
        await jira.create_issue(db, entry, item)
    assert sent["issuetype"]["name"] == "Content Tasks"
    assert not link, "no parent link without one"


async def test_issue_exists_rejects_leaf_types_as_parents(monkeypatch):
    """Jira's create call 400s with 'Please select valid parent issue' when the
    key names a Content Task or subtask — existing isn't enough, the type has
    to be able to have children. issue_exists must catch that upfront rather
    than let it surface only when create_issue actually tries to use it."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path.rsplit("/", 1)[-1]
        types = {
            "TCE-1": "Content Requests",
            "TCE-2": "Content Tasks",
            "TCE-3": "TCE subtask",
        }
        if key not in types:
            return httpx.Response(404, json={})
        return httpx.Response(200, json={"fields": {"issuetype": {"name": types[key]}}})

    monkeypatch.setattr(jira, "_client", transport(handler))

    async with Session() as db:
        assert await jira.issue_exists(db, "TCE-1") is True
        assert await jira.issue_exists(db, "TCE-2") is False
        assert await jira.issue_exists(db, "TCE-3") is False
        assert await jira.issue_exists(db, "TCE-404") is False


def test_title_leads_with_work_and_customer_over_notes():
    """A Jira issue list should be scannable without opening each ticket —
    task type, then customer, then what the notes actually say."""
    from types import SimpleNamespace as N

    entry = N(member=N(display_name="Ada"), entry_date=DAY)
    item = N(
        task_type=N(name="Documentation"),
        customer="Acme Corp",
        notes="fix the onboarding guide typo\nsecond line ignored",
    )

    assert (
        jira._title(entry, item)
        == "Documentation — Acme Corp: fix the onboarding guide typo"
    )


def test_title_falls_back_to_who_and_when_without_notes():
    """A freshly-planned item usually has no notes yet — the title shouldn't
    end in a bare colon."""
    from types import SimpleNamespace as N

    entry = N(member=N(display_name="Ada"), entry_date=DAY)
    item = N(task_type=N(name="Documentation"), customer=None, notes=None)

    assert jira._title(entry, item) == f"Documentation: Ada · {DAY}"


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

    entry = N(
        kind="plan",
        entry_date="2030-07-08",
        source="web",
        raw_text=None,
        member=N(display_name="Ada", jira_account_id=None),
    )
    item = N(
        task_type=N(name="Documentation"),
        question_types=[],
        customer=None,
        count=None,
        notes=None,
        due_at=None,
        effort_minutes=None,
        pipeline="content_task",
        parent_issue_key=None,
    )
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

    entry = N(
        kind="plan",
        entry_date="2030-07-08",
        source="web",
        raw_text=None,
        member=N(display_name="Ada", jira_account_id=None),
    )
    item = N(
        task_type=N(name="Documentation"),
        question_types=[],
        customer=None,
        count=None,
        notes=None,
        due_at=None,
        effort_minutes=None,
        pipeline="content_task",
        parent_issue_key=None,
    )
    async with Session() as db:
        with pytest.raises(RuntimeError, match="bad field"):
            await jira.create_issue(db, entry, item)
    assert len(calls) == 1, "no retry on a 4xx"
