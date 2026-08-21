"""Jira Cloud v3 — one issue per task, plus status transitions.

Async port of the Django tracker's jira_client.py. Two behaviours are carried
over verbatim because they encode real quirks of the TCE workflow:

  * "Done" isn't reachable from "To Do" — you must step through "In Progress".
  * The Done transition has validators requiring Task Type / Question type /
    Test count / Effort Logged, even though the schema marks them optional.

Everything that was hardcoded there now lives in `integration_settings`.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import date
from typing import Any

import httpx
from sqlalchemy import select

from core.config import settings
from core.database import Session
from core.orm import PIPELINES, AuditLog, DailyEntry, EntryItem, IntegrationSetting

log = logging.getLogger(__name__)

# Inverse of core.orm.PIPELINES, so the two never drift apart.
ISSUE_TYPES = {slug: name for name, slug in PIPELINES.items()}
# Only these carry a customer field in Jira.
CUSTOMER_TYPES = {"Content Requests"}
# Leaf-level types this app creates or Jira already treats as a leaf — Jira's
# hierarchy refuses to let either kind parent another issue.
NON_PARENT_TYPES = {"Content Tasks", "TCE subtask"}

DEFAULTS: dict[str, Any] = {
    "project_key": "TCE",
    "issue_type": "Content Tasks",
    "customer_field": "customfield_10225",
    # Content Tasks and their container types are the same Jira hierarchy
    # level, so `parent` can't link them — this issue-link type carries that
    # relationship instead. "Relates" is the only generic type this project
    # has; swap it for a dedicated one if TCE ever adds "is part of".
    "parent_link_type": "Relates",
    "status_names": {
        "open": ["To Do"], "in_progress": ["In Progress"],
        "blocked": ["Blocked"], "closed": ["Done"],
    },
    # Validator-required custom fields on the Done transition, with the neutral
    # fallbacks the Django client used.
    "done_fields": {
        "task_type": "customfield_10230",
        "question_count": "customfield_10233",
        "test_count": "customfield_10234",
        "question_type": "customfield_10235",
        "due_at": "customfield_10521",
        "effort_logged": "customfield_10526",
        "question_type_fallback_id": "10244",
    },
}


class JiraDisabled(Exception):
    """No credentials, or writes are switched off. Callers treat this as skip."""


def _writes_allowed() -> None:
    """Guard on every mutating call. Reads never go through this."""
    if not settings.JIRA_WRITES_ENABLED:
        raise JiraDisabled("JIRA_WRITES_ENABLED is off — no issue was created or moved")


async def config(db) -> dict[str, Any]:
    if not (settings.JIRA_API_TOKEN and settings.JIRA_EMAIL and settings.JIRA_BASE_URL):
        raise JiraDisabled("JIRA_EMAIL / JIRA_API_TOKEN not set")
    row = await db.get(IntegrationSetting, "jira")
    return {**DEFAULTS, **(row.value if row else {})}


async def _send(c: httpx.AsyncClient, method: str, path: str, **kw) -> httpx.Response:
    """One retry policy for every Jira call.

    429 carries Retry-After and must be obeyed — ignoring it is how an account
    gets throttled harder. 5xx is transient, so back off. 4xx is our mistake and
    retrying just repeats it, so it returns immediately.
    """
    delay = 1.0
    for attempt in range(4):
        r = await c.request(method, path, **kw)
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After") or delay)
            log.warning("jira rate limited, waiting %.1fs (attempt %d)", wait, attempt + 1)
            await asyncio.sleep(min(wait, 60))
        elif 500 <= r.status_code < 600:
            log.warning("jira %s on %s, retrying in %.1fs", r.status_code, path, delay)
            await asyncio.sleep(delay)
        else:
            return r
        delay *= 2
    return r


def _client() -> httpx.AsyncClient:
    auth = base64.b64encode(
        f"{settings.JIRA_EMAIL}:{settings.JIRA_API_TOKEN}".encode()
    ).decode()
    return httpx.AsyncClient(
        base_url=settings.JIRA_BASE_URL,
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
        timeout=20,
    )


def _explain(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:200]}"
    detail = body.get("errorMessages") or [f"{k}: {v}" for k, v in (body.get("errors") or {}).items()]
    return f"HTTP {r.status_code}: {'; '.join(map(str, detail)) or r.text[:200]}"


async def issue_exists(db, key: str) -> bool:
    """A parent-eligibility check — Content Requests must reference a real,
    linkable parent issue, verified once at creation time rather than trusted
    blind. Reads are always allowed, so this runs regardless of
    JIRA_WRITES_ENABLED.

    Existing isn't enough: Jira's own hierarchy rejects a Content Task or a
    subtask as somebody else's parent ("Please select valid parent issue.")
    even though the key resolves fine, so that class of key must be treated
    as not-a-valid-parent here too rather than surfacing that 400 only once
    `create_issue` actually tries to use it.
    """
    await config(db)  # raises JiraDisabled if credentials aren't set
    async with _client() as c:
        r = await c.get(f"/rest/api/3/issue/{key}", params={"fields": "issuetype"})
    if r.status_code == 404:
        return False
    if r.status_code >= 400:
        raise RuntimeError(_explain(r))
    issue_type = r.json()["fields"]["issuetype"]["name"]
    return issue_type not in NON_PARENT_TYPES


def _adf(text: str) -> dict:
    return {
        "type": "doc", "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}] if line else []}
            for line in (text or "").split("\n")
        ],
    }


async def option_ids(db, c: httpx.AsyncClient, cfg: dict, issue_type: str) -> dict[str, dict]:
    """Jira wants option *ids*, not the labels we store. Fetch the map once from
    createmeta and cache it — 45 Task Types and 11 Question types that change
    about never. Refreshed by deleting the `jira_options` settings row."""
    key = f"jira_options:{issue_type}"
    if (row := await db.get(IntegrationSetting, key)) is not None:
        return row.value

    r = await c.get("/rest/api/3/issue/createmeta/TCE/issuetypes")
    # Jira's own issue type names carry stray whitespace ("HC Request " with a
    # trailing space) that ours never will, so a bare lookup missed real types.
    types = {t["name"].strip(): t["id"] for t in r.json().get("issueTypes", [])}
    issue_type = issue_type.strip()
    if issue_type not in types:
        raise RuntimeError(f"Jira has no issue type {issue_type!r}")
    r = await c.get(f"/rest/api/3/issue/createmeta/TCE/issuetypes/{types[issue_type]}")
    fields = {f["fieldId"]: f for f in r.json().get("fields", [])}

    f = cfg["done_fields"]
    value = {
        name: {o["value"]: o["id"] for o in (fields.get(fid, {}).get("allowedValues") or [])}
        for name, fid in (("task_type", f["task_type"]), ("question_type", f["question_type"]))
    }
    db.add(IntegrationSetting(key=key, value=value))
    await db.commit()
    return value


def _find_option(options: dict[str, str], name: str) -> str | None:
    """Exact match first, then case/whitespace-insensitive — Jira's picklist
    label and our stored name have drifted before (`Other` vs `Others`)."""
    if (id_ := options.get(name)) is not None:
        return id_
    folded = name.strip().casefold()
    for label, id_ in options.items():
        if label.strip().casefold() == folded:
            return id_
    return None


async def _account_id(db, c: httpx.AsyncClient, member) -> str | None:
    """`jira_account_id` was never written anywhere, so it was always empty and
    every issue landed unassigned — Jira's project default (a specific person,
    not "nobody") silently ate the assignment instead. Resolve it from the
    member's email on first use and cache it, so this self-heals per person
    instead of needing a manual admin step.
    """
    if member.jira_account_id:
        return member.jira_account_id
    if not getattr(member, "email", None):
        return None
    r = await c.get("/rest/api/3/user/search", params={"query": member.email, "maxResults": 1})
    users = r.json() if r.status_code < 400 else []
    if not isinstance(users, list) or not users:
        return None
    member.jira_account_id = users[0]["accountId"]
    await db.commit()
    return member.jira_account_id


def _title(entry: DailyEntry, item: EntryItem) -> str:
    """Task type first (what it is), customer next (who it's for), then a
    one-line notes excerpt — a Jira issue list should be scannable without
    opening each ticket. Notes are often absent on a freshly-planned item, so
    fall back to who/when rather than leaving a bare trailing colon."""
    lead = item.task_type.name
    if item.customer:
        lead += f" — {item.customer}"
    if item.notes:
        snippet = item.notes.strip().splitlines()[0]
        tail = snippet if len(snippet) <= 80 else snippet[:79] + "…"
    else:
        tail = f"{entry.member.display_name} · {entry.entry_date}"
    return f"{lead}: {tail}"[:254]


def _describe(entry: DailyEntry, item: EntryItem) -> str:
    lines = [
        f"ContentOps — {entry.kind.title()} — {entry.entry_date} — {entry.member.display_name}",
        f"Source: {entry.source}", "", f"Task: {item.task_type.name}",
    ]
    if item.question_type:
        lines.append(f"Question type: {item.question_type.name}")
    for label, value in (("Customer", item.customer), ("Count", item.count)):
        if value is not None:
            lines.append(f"{label}: {value}")
    if item.notes:
        lines += ["", item.notes]
    return "\n".join(lines)


# ── writes ────────────────────────────────────────────────────────────────────


async def create_issue(db, entry: DailyEntry, item: EntryItem) -> tuple[str, str]:
    """Creates the issue carrying every field the analytics later read back.

    Sending only a summary produced tickets with no work type, no customer and
    no assignee — invisible to the reporting this app then does.

    Always a Content Task, regardless of `item.pipeline` — this app never
    files a new Content Request/HC Request/etc. issue of its own, it only
    ever spins off a task under an existing one. `pipeline` still names that
    existing parent's work type for reporting; it no longer picks what gets
    created here.

    The parent is carried as an issue *link*, not Jira's `parent` field —
    Content Tasks and their container types (Content Requests, HC Request,
    ...) all sit at the same hierarchy level in this project, and Jira's
    `parent` field only ever works one level down (Epic → standard, or
    standard → subtask). Setting it between two same-level issues 400s with
    "Please select valid parent issue" no matter how valid the key is.
    """
    cfg = await config(db)
    _writes_allowed()
    f = cfg["done_fields"]
    issue_type = cfg["issue_type"]

    fields: dict[str, Any] = {
        "project": {"key": cfg["project_key"]},
        "summary": _title(entry, item),
        "description": _adf(_describe(entry, item)),
        "issuetype": {"name": issue_type},
    }
    if item.due_at:
        fields["duedate"] = item.due_at.isoformat()
        fields[f["due_at"]] = item.due_at.isoformat()
    if item.count is not None:
        fields[f["question_count"]] = item.count
    if item.effort_minutes is not None:
        fields[f["effort_logged"]] = item.effort_minutes
    if item.customer and issue_type in CUSTOMER_TYPES:
        fields[cfg["customer_field"]] = item.customer

    async with _client() as c:
        if account_id := await _account_id(db, c, entry.member):
            fields["assignee"] = {"id": account_id}
        options = await option_ids(db, c, cfg, issue_type)
        # Task Type is required on Content Tasks; an unmapped name would 400.
        if tt := _find_option(options["task_type"], item.task_type.name):
            fields[f["task_type"]] = {"id": tt}
        else:
            log.warning(
                "no Jira task-type option matches %r for issue type %r — field left unset",
                item.task_type.name, issue_type,
            )
        if item.question_type and (qt := _find_option(options["question_type"], item.question_type.name)):
            fields[f["question_type"]] = [{"id": qt}]

        r = await _send(c, "POST", "/rest/api/3/issue", json={"fields": fields})
        if r.status_code >= 400:
            raise RuntimeError(_explain(r))
        key = r.json()["key"]
        if item.parent_issue_key:
            # Best-effort: the issue itself is already created at this point,
            # so a link failure shouldn't discard its key and orphan a ticket
            # (or, worse, get retried into a duplicate by the pending sweep).
            try:
                await _link_parent(c, cfg, key, item.parent_issue_key)
            except Exception as e:
                log.warning("created %s but failed to link it to parent %s: %s",
                            key, item.parent_issue_key, e)
    return key, f"{settings.JIRA_BASE_URL}/browse/{key}"


async def _link_parent(c: httpx.AsyncClient, cfg: dict, key: str, parent_key: str) -> None:
    r = await _send(c, "POST", "/rest/api/3/issueLink", json={
        "type": {"name": cfg["parent_link_type"]},
        "inwardIssue": {"key": key},
        "outwardIssue": {"key": parent_key},
    })
    if r.status_code >= 400:
        raise RuntimeError(_explain(r))


async def _done_fields(
    c: httpx.AsyncClient, cfg: dict, key: str, due_at: date | None,
    effort_minutes: int | None = None,
) -> dict:
    """Carry the issue's existing values back through the Done transition, so a
    validator never blocks the status change.

    Refuses to guess. If the read fails we raise rather than fall back to zeroes:
    Effort Logged is the team's entire time dataset, and a transient 429 must
    never be the reason someone's recorded hours become 0.
    """
    f = cfg["done_fields"]
    ids = ",".join(v for k, v in f.items() if k != "question_type_fallback_id")
    r = await _send(c, "GET", f"/rest/api/3/issue/{key}", params={"fields": ids})
    if r.status_code >= 400:
        raise RuntimeError(
            f"cannot read {key} before transitioning to Done ({_explain(r)}); "
            "refusing to write default values over existing fields"
        )
    cur = r.json().get("fields", {})

    out: dict[str, Any] = {}
    if (tt := cur.get(f["task_type"])) and tt.get("id"):
        out[f["task_type"]] = {"id": tt["id"]}

    qt = cur.get(f["question_type"])
    if isinstance(qt, list) and qt:
        out[f["question_type"]] = [{"id": str(v["id"])} for v in qt if v.get("id")]
    elif isinstance(qt, dict) and qt.get("id"):
        out[f["question_type"]] = [{"id": str(qt["id"])}]
    else:
        out[f["question_type"]] = [{"id": f["question_type_fallback_id"]}]

    for name in ("question_count", "test_count"):
        out[f[name]] = cur.get(f[name]) or 0

    # Our minutes win when we have them; otherwise keep whatever Jira holds,
    # including a genuine 0. Never invent a value.
    existing_effort = cur.get(f["effort_logged"])
    if effort_minutes is not None:
        out[f["effort_logged"]] = effort_minutes
    elif existing_effort is not None:
        out[f["effort_logged"]] = existing_effort
    if due := (due_at.isoformat() if due_at else cur.get(f["due_at"])):
        out[f["due_at"]] = str(due)[:10]
    return out


def _pick(transitions: list[dict], want: set[str]) -> dict | None:
    for t in transitions:
        if ((t.get("to") or {}).get("name") or "").strip().lower() in want:
            return t
    for t in transitions:  # loose match: "Done" vs "Done ✅"
        name = ((t.get("to") or {}).get("name") or "").strip().lower()
        if any(w in name or name in w for w in want):
            return t
    return None


async def transition(db, key: str, status: str, *, comment: str | None = None,
                     due_at: date | None = None, effort_minutes: int | None = None,
                     pipeline: str | None = None, task_type_name: str | None = None) -> None:
    cfg = await config(db)
    _writes_allowed()
    want = {n.lower() for n in cfg["status_names"].get(status, [])}

    async with _client() as c:
        async def options() -> list[dict]:
            r = await _send(c, "GET", f"/rest/api/3/issue/{key}/transitions",
                            params={"expand": "transitions.fields"})
            if r.status_code >= 400:
                raise RuntimeError(_explain(r))
            return r.json().get("transitions", [])

        available = await options()
        chosen = _pick(available, want)

        if chosen is None and status == "closed":
            # Done only appears once the issue is In Progress. Step through.
            step = _pick(available, {n.lower() for n in cfg["status_names"]["in_progress"]})
            if step:
                await _send(c, "POST", f"/rest/api/3/issue/{key}/transitions",
                            json={"transition": {"id": step["id"]}})
                chosen = _pick(await options(), want)

        if chosen is None:
            names = [(t.get("to") or {}).get("name") for t in available]
            raise RuntimeError(f"No transition to {status!r}. Available: {names}")

        payload: dict[str, Any] = {"transition": {"id": chosen["id"]}}
        fields: dict[str, Any] = {}
        if status == "closed":
            fields = await _done_fields(c, cfg, key, due_at, effort_minutes)
        elif due_at:
            for fk, fv in (chosen.get("fields") or {}).items():
                if "due" in str((fv or {}).get("name", "")).lower():
                    fields[fk] = due_at.isoformat()
                    break
        # Set on the transition itself, not a follow-up call: a workflow
        # transition can carry its own field defaults/validators, which — for
        # a Done transition in particular — silently reset Task Type if it
        # isn't part of THIS request. A later "fix it up" call is too late to
        # stop that from ever having happened. Overwrites whatever
        # `_done_fields` read back from Jira, so our freshly-chosen type
        # always wins over Jira's currently-stored one.
        if task_type_name:
            issue_type = ISSUE_TYPES.get(pipeline, cfg["issue_type"]) if pipeline else cfg["issue_type"]
            options_map = await option_ids(db, c, cfg, issue_type)
            if tt := _find_option(options_map["task_type"], task_type_name):
                fields[cfg["done_fields"]["task_type"]] = {"id": tt}
        if fields:
            payload["fields"] = fields
        if comment and comment.strip():
            payload["update"] = {"comment": [{"add": {"body": _adf(comment.strip())}}]}

        r = await _send(c, "POST", f"/rest/api/3/issue/{key}/transitions", json=payload)
        if r.status_code >= 400:
            # A workflow that doesn't expose the due-date field on its screen
            # rejects the whole payload — retry bare so the status still moves.
            r = await _send(c, "POST", f"/rest/api/3/issue/{key}/transitions",
                            json={"transition": {"id": chosen["id"]}})
            if r.status_code >= 400:
                raise RuntimeError(_explain(r))


# ── background workers ────────────────────────────────────────────────────────


async def _audit(db, action: str, item: EntryItem, detail: dict) -> None:
    """audit_log has existed unused since the schema was written. Every Jira
    write lands here, so "who made this ticket" is answerable."""
    db.add(AuditLog(
        action=action, entity_type="entry_item", entity_id=str(item.id),
        payload={"jira_issue_key": item.jira_issue_key, **detail},
    ))


async def push_item(item_id: int) -> None:
    """Create the Jira issue for one item. Runs after the response is sent, so
    a slow or broken Jira never blocks someone saving their plan."""
    async with Session() as db:
        item = await db.get(EntryItem, item_id)
        if item is None or item.jira_issue_key:
            return
        entry = await db.get(DailyEntry, item.entry_id)
        try:
            key, url = await create_issue(db, entry, item)
            item.jira_issue_key, item.jira_issue_url = key, url
            item.jira_state, item.jira_error = "ok", None
            await _audit(db, "jira.create", item, {"pipeline": item.pipeline})
            if item.status != "open":
                # Just created as a Content Task above, whatever `item.pipeline`
                # says — the option lookup below must match that, not the
                # reporting pipeline, or it fetches the wrong issue type's
                # Task Type dropdown for the ticket that actually exists.
                await transition(db, key, item.status, comment=item.notes,
                                 due_at=item.due_at, effort_minutes=item.effort_minutes,
                                 task_type_name=item.task_type.name)
        except JiraDisabled as e:
            item.jira_state, item.jira_error = "none", str(e)
        except Exception as e:
            item.jira_state, item.jira_error = "failed", str(e)[:500]
            log.warning("jira push failed for item %s: %s", item_id, e)
        await db.commit()


async def push_status(item_id: int, status: str, note: str | None = None) -> None:
    """Moves the Jira issue, syncs our effort onto it, and reasserts task type
    on the same transition call — see `transition()`'s task_type_name."""
    async with Session() as db:
        item = await db.get(EntryItem, item_id)
        if item is None or not item.jira_issue_key:
            return
        try:
            await transition(db, item.jira_issue_key, status, comment=note,
                             due_at=item.due_at, effort_minutes=item.effort_minutes,
                             pipeline=item.pipeline, task_type_name=item.task_type.name)
            item.jira_state, item.jira_error = "ok", None
            await _audit(db, "jira.transition", item,
                         {"to": status, "effort_minutes": item.effort_minutes})
        except JiraDisabled:
            return
        except Exception as e:
            item.jira_state, item.jira_error = "failed", str(e)[:500]
            log.warning("jira transition failed for item %s: %s", item_id, e)
        await db.commit()


async def push_fields(item_id: int) -> None:
    """Re-syncs summary and task type onto an existing issue after an edit.
    Without this, editing notes or task type only ever updated our own
    dashboard — the Jira issue silently drifted out of date."""
    async with Session() as db:
        item = await db.get(EntryItem, item_id)
        if item is None or not item.jira_issue_key:
            return
        entry = await db.get(DailyEntry, item.entry_id)
        try:
            cfg = await config(db)
            _writes_allowed()
            f = cfg["done_fields"]
            issue_type = ISSUE_TYPES.get(item.pipeline, cfg["issue_type"])
            fields: dict[str, Any] = {"summary": _title(entry, item)}
            async with _client() as c:
                options = await option_ids(db, c, cfg, issue_type)
                if tt := _find_option(options["task_type"], item.task_type.name):
                    fields[f["task_type"]] = {"id": tt}
                r = await _send(
                    c, "PUT", f"/rest/api/3/issue/{item.jira_issue_key}", json={"fields": fields}
                )
            if r.status_code >= 400:
                raise RuntimeError(_explain(r))
            item.jira_state, item.jira_error = "ok", None
            await _audit(db, "jira.update_fields", item, {"summary": fields["summary"]})
        except JiraDisabled:
            return
        except Exception as e:
            item.jira_state, item.jira_error = "failed", str(e)[:500]
            log.warning("jira field sync failed for item %s: %s", item_id, e)
        await db.commit()


async def cancel_issue(key: str) -> None:
    """Best-effort: transition the Jira issue when its ContentOps ticket is
    deleted, so the delete doesn't leave an orphaned issue behind. The item
    row is already gone by the time this runs, so it takes the issue key
    directly rather than an item id."""
    async with Session() as db:
        try:
            cfg = await config(db)
            _writes_allowed()
        except JiraDisabled:
            return
        try:
            async with _client() as c:
                r = await _send(c, "GET", f"/rest/api/3/issue/{key}/transitions")
                if r.status_code >= 400:
                    raise RuntimeError(_explain(r))
                available = r.json().get("transitions", [])
                chosen = _pick(available, {"cancelled", "canceled", "won't do", "wont do", "rejected"})
                if chosen is None:
                    chosen = _pick(available, {n.lower() for n in cfg["status_names"]["closed"]})
                if chosen is None:
                    log.warning("no cancel/close transition available for %s after delete", key)
                    return
                r = await _send(c, "POST", f"/rest/api/3/issue/{key}/transitions",
                                json={"transition": {"id": chosen["id"]}})
                if r.status_code >= 400:
                    raise RuntimeError(_explain(r))
        except Exception as e:
            log.warning("jira cancel failed for %s: %s", key, e)


async def sweep_pending(limit: int = 25) -> int:
    """BackgroundTasks die with the process — a restart mid-write strands items
    on `pending`. This is the safety net that a real broker would provide."""
    async with Session() as db:
        ids = list(await db.scalars(
            select(EntryItem.id).where(EntryItem.jira_state == "pending").limit(limit)
        ))
    for item_id in ids:
        await push_item(item_id)
    return len(ids)
