"""Jira Cloud v3 — one issue per task, plus status transitions.

Async port of the Django tracker's jira_client.py. Two behaviours are carried
over verbatim because they encode real quirks of the TCE workflow:

  * "Done" isn't reachable from "To Do" — you must step through "In Progress".
  * The Done transition has validators requiring Task Type / Question type /
    Test count / Effort Logged, even though the schema marks them optional.

Everything that was hardcoded there now lives in `integration_settings`.
"""

from __future__ import annotations

import base64
import logging
from datetime import date
from typing import Any

import httpx
from sqlalchemy import select

from core.config import settings
from core.database import Session
from core.orm import DailyEntry, EntryItem, IntegrationSetting

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "project_key": "TCE",
    "issue_type": "Content Tasks",
    "summary_prefix": "[Plan]",
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
    """No credentials configured — callers treat this as skip, not failure."""


async def config(db) -> dict[str, Any]:
    if not (settings.JIRA_API_TOKEN and settings.JIRA_EMAIL and settings.JIRA_BASE_URL):
        raise JiraDisabled("JIRA_EMAIL / JIRA_API_TOKEN not set")
    row = await db.get(IntegrationSetting, "jira")
    return {**DEFAULTS, **(row.value if row else {})}


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


def _adf(text: str) -> dict:
    return {
        "type": "doc", "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}] if line else []}
            for line in (text or "").split("\n")
        ],
    }


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
    cfg = await config(db)
    fields = {
        "project": {"key": cfg["project_key"]},
        "summary": (f"{cfg['summary_prefix']} {item.task_type.name} · "
                    f"{entry.member.display_name} · {entry.entry_date}")[:254],
        "description": _adf(_describe(entry, item)),
        "issuetype": {"name": cfg["issue_type"]},
    }
    if item.due_at:
        fields["duedate"] = item.due_at.isoformat()

    async with _client() as c:
        r = await c.post("/rest/api/3/issue", json={"fields": fields})
    if r.status_code >= 400:
        raise RuntimeError(_explain(r))
    key = r.json()["key"]
    return key, f"{settings.JIRA_BASE_URL}/browse/{key}"


async def _done_fields(c: httpx.AsyncClient, cfg: dict, key: str, due_at: date | None) -> dict:
    """Carry the issue's existing values back through the Done transition, with
    neutral defaults, so a validator never blocks the status change."""
    f = cfg["done_fields"]
    ids = ",".join(v for k, v in f.items() if k != "question_type_fallback_id")
    r = await c.get(f"/rest/api/3/issue/{key}", params={"fields": ids})
    cur = r.json().get("fields", {}) if r.status_code < 400 else {}

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

    for name in ("question_count", "test_count", "effort_logged"):
        out[f[name]] = cur.get(f[name]) or 0
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
                     due_at: date | None = None) -> None:
    cfg = await config(db)
    want = {n.lower() for n in cfg["status_names"].get(status, [])}

    async with _client() as c:
        async def options() -> list[dict]:
            r = await c.get(f"/rest/api/3/issue/{key}/transitions",
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
                await c.post(f"/rest/api/3/issue/{key}/transitions",
                             json={"transition": {"id": step["id"]}})
                chosen = _pick(await options(), want)

        if chosen is None:
            names = [(t.get("to") or {}).get("name") for t in available]
            raise RuntimeError(f"No transition to {status!r}. Available: {names}")

        payload: dict[str, Any] = {"transition": {"id": chosen["id"]}}
        if status == "closed":
            payload["fields"] = await _done_fields(c, cfg, key, due_at)
        elif due_at:
            for fk, fv in (chosen.get("fields") or {}).items():
                if "due" in str((fv or {}).get("name", "")).lower():
                    payload["fields"] = {fk: due_at.isoformat()}
                    break
        if comment and comment.strip():
            payload["update"] = {"comment": [{"add": {"body": _adf(comment.strip())}}]}

        r = await c.post(f"/rest/api/3/issue/{key}/transitions", json=payload)
        if r.status_code >= 400:
            # A workflow that doesn't expose the due-date field on its screen
            # rejects the whole payload — retry bare so the status still moves.
            r = await c.post(f"/rest/api/3/issue/{key}/transitions",
                             json={"transition": {"id": chosen["id"]}})
            if r.status_code >= 400:
                raise RuntimeError(_explain(r))


# ── background workers ────────────────────────────────────────────────────────


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
            if item.status != "open":
                await transition(db, key, item.status, comment=item.notes, due_at=item.due_at)
        except JiraDisabled as e:
            item.jira_state, item.jira_error = "none", str(e)
        except Exception as e:
            item.jira_state, item.jira_error = "failed", str(e)[:500]
            log.warning("jira push failed for item %s: %s", item_id, e)
        await db.commit()


async def push_status(item_id: int, status: str, note: str | None = None) -> None:
    async with Session() as db:
        item = await db.get(EntryItem, item_id)
        if item is None or not item.jira_issue_key:
            return
        try:
            await transition(db, item.jira_issue_key, status, comment=note, due_at=item.due_at)
            item.jira_state, item.jira_error = "ok", None
        except JiraDisabled:
            return
        except Exception as e:
            item.jira_state, item.jira_error = "failed", str(e)[:500]
            log.warning("jira transition failed for item %s: %s", item_id, e)
        await db.commit()


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
