"""Mirror Jira's "Content Issue" requests (project TCE, issue type Content
Requests, request type = Content Issue) into Postgres — same
page/upsert/replace pattern as content_requests.py, plus the 5 custom fields
the weekly Slack digest and the Content Issue Analysis tab both need.

Custom field IDs are Jira-instance-specific and not guessable, so they're
discovered once from /rest/api/3/field and cached in `integration_settings`
rather than hardcoded — a wrong guess would silently zero out every impact
number instead of failing loudly.

No date filter in the JQL: like ContentRequest, this fully re-mirrors the
board every run rather than tracking a high-water mark, so a single sync
already covers all history Jira has for this request type (August onward,
and everything before it). Weekly vs. monthly is just a `created_at` range
picked at query time — no separate snapshot tables.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from core.config import settings
from core.database import Session
from core.orm import ContentIssue, IntegrationSetting, SyncCursor
from integrations.jira import JiraDisabled, _client, _explain, config

log = logging.getLogger(__name__)

CURSOR = "content_issues"
FIELD_SETTING_KEY = "content_issue_fields"

# The Content Issue Analysis tab only cares about August 2026 onward — this
# request type existed in Jira long before that (2025 tickets included), and
# an unbounded JQL pulled all of it in. Bounding the JQL itself means a stray
# older ticket never re-enters on the next sync; it isn't just filtered out
# after the fact.
DEFAULT_FROM = date(2026, 8, 1)

JQL = (
    'project = {project} AND type = "Content Requests" '
    'AND "request type[dropdown]" = "Content Issue" '
    'AND created >= "{frm}" ORDER BY created DESC'
)

# name (lowercased) -> our column key. Substring match, same rule the
# discovery script this was ported from used — first field whose name
# contains the phrase wins.
SUBSTRING_FIELDS = {
    "content issue status": "content_issue_status",
    "# of customers impacted": "customers_impacted",
    "# of test slugs impacted": "test_slugs_impacted",
    "# of candidates impacted": "candidates_impacted",
    "setter id last modified by": "setter_last_modified",
}
# Exact match only — "setter" is a substring of "setter id last modified by"
# and would otherwise grab whichever field the loop reaches first.
EXACT_FIELDS = {"setter": "setter"}


class _AuthFailed(RuntimeError):
    """Token rejected — stop the timer retrying until someone fixes it."""


async def _field_ids(db) -> dict[str, str]:
    row = await db.get(IntegrationSetting, FIELD_SETTING_KEY)
    if row and row.value:
        return row.value

    async with _client() as c:
        r = await c.get("/rest/api/3/field")
        if r.status_code >= 400:
            raise RuntimeError(_explain(r))
        fields = r.json()

    field_map: dict[str, str] = {}
    for f in fields:
        name = f["name"].lower().strip()
        for target, key in EXACT_FIELDS.items():
            if name == target:
                field_map[key] = f["id"]
        for target, key in SUBSTRING_FIELDS.items():
            if target in name and key not in field_map:
                field_map[key] = f["id"]

    await db.execute(
        insert(IntegrationSetting)
        .values(key=FIELD_SETTING_KEY, value=field_map)
        .on_conflict_do_update(index_elements=["key"], set_={"value": field_map})
    )
    return field_map


def _to_int(v) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    return 0


def _name(v) -> str | None:
    if isinstance(v, dict):
        return v.get("displayName") or v.get("value") or v.get("name")
    if isinstance(v, str):
        return v.strip() or None
    return None


def _status(v) -> str:
    text = (_name(v) or "").lower()
    if "invalid" in text:
        return "invalid"
    if "platform" in text:
        return "platform_issue"
    if "valid" in text:
        return "valid"
    if "customer" in text:
        return "customer"
    return "unknown"


def _row(issue: dict, field_ids: dict[str, str], base_url: str) -> dict:
    f = issue.get("fields") or {}

    def get(key: str):
        return f.get(field_ids[key]) if field_ids.get(key) else None

    created = f.get("created")
    return {
        "issue_key": issue["key"],
        "summary": f.get("summary") or "",
        "content_issue_status": _status(get("content_issue_status")),
        "setter": _name(get("setter")),
        "setter_last_modified": _name(get("setter_last_modified")),
        "test_slugs_impacted": _to_int(get("test_slugs_impacted")),
        "candidates_impacted": _to_int(get("candidates_impacted")),
        "customers_impacted": _to_int(get("customers_impacted")),
        "created_at": datetime.fromisoformat(created) if created else None,
        "url": f"{base_url}/browse/{issue['key']}",
        "synced_at": func.now(),
    }


async def sync(force: bool = False) -> dict:
    """Paginate the board and upsert. Safe to run on a timer or on demand —
    the Friday scheduler job and a manual "sync now" both call this."""
    async with Session() as db:
        try:
            cfg = await config(db)
        except JiraDisabled as e:
            await _mark(db, "disabled", str(e))
            await db.commit()
            return {"ok": False, "reason": str(e)}

        cursor = await db.get(SyncCursor, CURSOR)
        if not force and cursor and cursor.last_status == "auth_failed":
            return {"ok": False, "reason": cursor.last_error, "skipped": True}

        rows, seen = [], set()
        try:
            field_ids = await _field_ids(db)
            async with _client() as c:
                # This instance's /search/jql answers with nextPageToken/isLast,
                # not the classic startAt/total — trusting `total` here (as
                # content_requests.py does) silently truncates at the first
                # page. Follow the token until isLast is true instead.
                page_token: str | None = None
                while True:
                    params = {
                        "jql": JQL.format(
                            project=cfg["project_key"], frm=DEFAULT_FROM.isoformat()
                        ),
                        "maxResults": 100,
                        "fields": "summary,created," + ",".join(field_ids.values()),
                    }
                    if page_token:
                        params["nextPageToken"] = page_token
                    r = await c.get("/rest/api/3/search/jql", params=params)
                    if r.status_code >= 400:
                        raise RuntimeError(_explain(r))
                    body = r.json()
                    issues = body.get("issues") or []
                    for issue in issues:
                        if issue["key"] not in seen:
                            seen.add(issue["key"])
                            rows.append(_row(issue, field_ids, settings.JIRA_BASE_URL))
                    page_token = body.get("nextPageToken")
                    if body.get("isLast", True) or not page_token or not issues:
                        break

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
            await db.commit()
            log.warning("content issue sync failed: %s", e)
            return {"ok": False, "reason": str(e)[:200]}

        for row in rows:
            stmt = insert(ContentIssue).values(**row)
            await db.execute(
                stmt.on_conflict_do_update(
                    index_elements=["issue_key"],
                    set_={k: v for k, v in row.items() if k != "issue_key"},
                )
            )
        # Belt and braces alongside the JQL's own `created >= DEFAULT_FROM`:
        # an issue's `created` date in Jira can't retroactively change, but a
        # stray pre-cutoff row (from before this bound existed, or a manual
        # insert) would otherwise sit there forever — upserts only add/update,
        # they never remove. This keeps "table only ever holds DEFAULT_FROM
        # onward" true regardless of how a row got in.
        deleted = await db.execute(
            delete(ContentIssue).where(
                ContentIssue.created_at
                < datetime.combine(DEFAULT_FROM, datetime.min.time())
            )
        )
        await _mark(db, "ok", None)
        await db.commit()
        return {"ok": True, "synced": len(rows), "purged": deleted.rowcount}


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


def _daily_buckets(frm: date, to: date, rows: list[ContentIssue]) -> list[dict]:
    """Zero-filled per-day counts across the whole range, not just days with
    activity — a gap in the bars is real information (no issues that day),
    not a missing row the chart should skip over."""
    buckets = {
        (frm + timedelta(days=i)): {
            "valid": 0,
            "invalid": 0,
            "customer": 0,
            "platform_issue": 0,
            "unknown": 0,
        }
        for i in range((to - frm).days + 1)
    }
    for row in rows:
        d = row.created_at.date() if row.created_at else None
        if d in buckets:
            key = (
                row.content_issue_status
                if row.content_issue_status in buckets[d]
                else "unknown"
            )
            buckets[d][key] += 1
    return [{"date": d.isoformat(), **counts} for d, counts in sorted(buckets.items())]


async def overview(db, frm: date, to: date) -> dict:
    # A plain range on `created_at`, not `func.date(created_at) BETWEEN ...` —
    # wrapping the column in a function makes Postgres discard
    # ix_content_issues_created and sequential-scan the whole table on every
    # request. Cheap today at a few hundred rows; this table only grows
    # (full-history mirror, never trimmed), so the difference compounds.
    start = datetime.combine(frm, datetime.min.time())
    end = datetime.combine(to + timedelta(days=1), datetime.min.time())
    rows = list(
        await db.scalars(
            select(ContentIssue).where(
                ContentIssue.created_at >= start,
                ContentIssue.created_at < end,
            )
        )
    )

    valid = [r for r in rows if r.content_issue_status == "valid"]
    invalid = [r for r in rows if r.content_issue_status == "invalid"]
    customer = [r for r in rows if r.content_issue_status == "customer"]
    platform = [r for r in rows if r.content_issue_status == "platform_issue"]
    # Not yet triaged in Jira — kept separate rather than dropped, so
    # valid + invalid + customer + platform + unknown always reconciles with total.
    unknown = [
        r
        for r in rows
        if r.content_issue_status
        not in ("valid", "invalid", "customer", "platform_issue")
    ]

    setter_issues: dict[tuple[str, str], list[ContentIssue]] = {}
    for r in valid:
        key = (r.setter or "Unknown", r.setter_last_modified or "Unknown")
        setter_issues.setdefault(key, []).append(r)

    return {
        "total": len(rows),
        "valid_count": len(valid),
        "invalid_count": len(invalid),
        "customer_count": len(customer),
        "platform_count": len(platform),
        "unknown_count": len(unknown),
        "impact": {
            "tests_impacted": sum(r.test_slugs_impacted for r in valid),
            "candidates_impacted": sum(r.candidates_impacted for r in valid),
            "customers_impacted": sum(r.customers_impacted for r in valid),
        },
        "setters": [
            {
                "setter": setter,
                "setter_last_modified": last_mod,
                "count": len(issues),
                "issues": [{"issue_key": i.issue_key, "url": i.url} for i in issues],
            }
            for (setter, last_mod), issues in sorted(setter_issues.items())
        ],
        "daily": _daily_buckets(frm, to, rows),
    }
