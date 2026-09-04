"""Mirror the Jira Content Requests board into Postgres.

The Django page ran a JQL query plus full board pagination on *every* page load
and stored nothing — so it was slow and no history existed. This syncs on a
timer instead, which also makes created-vs-resolved trends possible at all.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from core.config import settings
from core.database import Session
from core.orm import ContentRequest, SyncCursor
from integrations.jira import JiraDisabled, _client, _explain, config

log = logging.getLogger(__name__)

CURSOR = "content_requests"


class _AuthFailed(RuntimeError):
    """Token rejected — stop the timer retrying until someone fixes it."""


FIELDS = (
    "summary,status,assignee,reporter,priority,created,updated,"
    "labels,issuetype,duedate,resolutiondate"
)
JQL = 'project = {project} AND issuetype = "Content Requests" ORDER BY created DESC'


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row(issue: dict) -> dict:
    f = issue.get("fields") or {}
    status = f.get("status") or {}
    assignee = f.get("assignee") or {}
    return {
        "issue_key": issue["key"],
        "summary": f.get("summary") or "",
        "status": status.get("name") or "Unknown",
        "status_category": ((status.get("statusCategory") or {}).get("name")),
        "assignee": assignee.get("displayName") or "Unassigned",
        "reporter": (f.get("reporter") or {}).get("displayName"),
        "priority": (f.get("priority") or {}).get("name") or "None",
        "issue_type": (f.get("issuetype") or {}).get("name"),
        "labels": f.get("labels") or [],
        "created_at": _dt(f.get("created")),
        "updated_at": _dt(f.get("updated")),
        "due_date": date.fromisoformat(f["duedate"]) if f.get("duedate") else None,
        "resolved_at": _dt(f.get("resolutiondate")),
        "url": f"{settings.JIRA_BASE_URL}/browse/{issue['key']}",
        "raw": {},
        "synced_at": func.now(),
    }


async def sync(force: bool = False) -> dict:
    """Paginate the board and upsert. Safe to run on a timer or on demand."""
    async with Session() as db:
        try:
            cfg = await config(db)
        except JiraDisabled as e:
            await _mark(db, "disabled", str(e))
            return {"ok": False, "reason": str(e)}

        # Don't re-poll on a credential the server already rejected — the timer
        # would otherwise 401 every 15 minutes forever. POST /sync clears it.
        cursor = await db.get(SyncCursor, CURSOR)
        if not force and cursor and cursor.last_status == "auth_failed":
            return {"ok": False, "reason": cursor.last_error, "skipped": True}

        rows, start, seen = [], 0, set()
        try:
            async with _client() as c:
                while True:
                    r = await c.get(
                        "/rest/api/3/search/jql",
                        params={
                            "jql": JQL.format(project=cfg["project_key"]),
                            "startAt": start,
                            "maxResults": 100,
                            "fields": FIELDS,
                        },
                    )
                    if r.status_code >= 400:
                        raise RuntimeError(_explain(r))
                    body = r.json()
                    issues = body.get("issues") or []
                    for issue in issues:
                        if issue["key"] not in seen:
                            seen.add(issue["key"])
                            rows.append(_row(issue))
                    start += len(issues)
                    if not issues or start >= body.get("total", 0):
                        break

                # /search/jql answers 200 {"issues": []} when the credentials
                # are rejected, so an empty board and a dead token look the
                # same. Confirm the token before trusting the empty result.
                if not rows:
                    who = await c.get("/rest/api/3/myself")
                    if who.status_code >= 400:
                        raise _AuthFailed(f"credentials rejected: {_explain(who)}")
        except Exception as e:
            await _mark(
                db,
                "auth_failed" if isinstance(e, _AuthFailed) else "error",
                str(e)[:500],
            )
            log.warning("content request sync failed: %s", e)
            return {"ok": False, "reason": str(e)[:200]}

        for row in rows:
            stmt = insert(ContentRequest).values(**row)
            await db.execute(
                stmt.on_conflict_do_update(
                    index_elements=["issue_key"],
                    set_={k: v for k, v in row.items() if k != "issue_key"},
                )
            )
        await _mark(db, "ok", None)
        await db.commit()
        return {"ok": True, "synced": len(rows)}


async def _mark(db, status: str, error: str | None) -> None:
    await db.execute(
        insert(SyncCursor)
        .values(
            key=CURSOR, last_synced_at=func.now(), last_status=status, last_error=error
        )
        .on_conflict_do_update(
            index_elements=["key"],
            set_={
                "last_synced_at": func.now(),
                "last_status": status,
                "last_error": error,
            },
        )
    )
    await db.commit()


async def query(
    db,
    *,
    status=None,
    assignee=None,
    priority=None,
    issue_type=None,
    frm: date | None = None,
    to: date | None = None,
    q=None,
    page=1,
    page_size=25,
) -> dict:
    where = []
    for column, value in (
        (ContentRequest.status, status),
        (ContentRequest.assignee, assignee),
        (ContentRequest.priority, priority),
        (ContentRequest.issue_type, issue_type),
    ):
        if value:
            where.append(column == value)
    if frm:
        where.append(ContentRequest.created_at >= frm)
    if to:
        # A plain upper-bound comparison, not `func.date(created_at) <= to` —
        # wrapping the column in a function stops Postgres from using
        # ix_cr_created and forces a sequential scan on every request.
        where.append(ContentRequest.created_at < to + timedelta(days=1))
    if q:
        where.append(ContentRequest.summary.ilike(f"%{q}%"))

    total = await db.scalar(
        select(func.count()).select_from(ContentRequest).where(*where)
    )
    rows = await db.scalars(
        select(ContentRequest)
        .where(*where)
        .order_by(ContentRequest.created_at.desc().nullslast())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return {
        "items": [
            {
                k: getattr(r, k)
                for k in (
                    "issue_key",
                    "summary",
                    "status",
                    "status_category",
                    "assignee",
                    "reporter",
                    "priority",
                    "issue_type",
                    "labels",
                    "created_at",
                    "updated_at",
                    "due_date",
                    "resolved_at",
                    "url",
                )
            }
            for r in rows
        ],
        "total": total or 0,
        "page": page,
        "page_size": page_size,
    }


async def facets(db) -> dict:
    async def distinct(column):
        return [
            v
            for (v,) in await db.execute(
                select(column).where(column.isnot(None)).distinct().order_by(column)
            )
        ]

    return {
        "statuses": await distinct(ContentRequest.status),
        "assignees": await distinct(ContentRequest.assignee),
        "priorities": await distinct(ContentRequest.priority),
        "issue_types": await distinct(ContentRequest.issue_type),
    }


async def stats(db, frm: date | None = None, to: date | None = None) -> dict:
    where = []
    if frm:
        where.append(ContentRequest.created_at >= frm)
    if to:
        where.append(ContentRequest.created_at < to + timedelta(days=1))

    async def group(column):
        return [
            {"key": k, "count": n}
            for k, n in await db.execute(
                select(column, func.count())
                .where(*where)
                .group_by(column)
                .order_by(func.count().desc())
            )
        ]

    open_backlog = await db.scalar(
        select(func.count())
        .select_from(ContentRequest)
        .where(ContentRequest.resolved_at.is_(None))
    )
    return {
        "total": await db.scalar(
            select(func.count()).select_from(ContentRequest).where(*where)
        ),
        "open_backlog": open_backlog or 0,
        "by_status": await group(ContentRequest.status),
        "by_assignee": await group(ContentRequest.assignee),
        "by_priority": await group(ContentRequest.priority),
    }
