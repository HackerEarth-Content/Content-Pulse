"""Load Jira history into ContentOps.

    uv run python -m scripts.backfill_jira --dry-run
    uv run python -m scripts.backfill_jira --from 2026-05-04

Reads Jira, writes only our own database — no Jira write is ever issued from
here. Idempotent on `jira_issue_key`, so it doubles as the nightly incremental.

Imported issues become ordinary `entry_items` under one synthetic plan entry per
member per day. Every existing aggregate then works on the history unchanged —
they already group by member, task type, question type, customer and date.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import collections
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import func, select

from core.config import settings
from core.database import Session
from core.orm import (
    DailyEntry,
    EntryItem,
    EntryItemStatusEvent,
    Member,
    MemberAlias,
    QuestionType,
    SyncCursor,
    entry_item_question_types,
    TaskType,
    pipeline_for,
)

CURSOR = "jira_backfill"
DEFAULT_FROM = date(2026, 5, 4)

# Minutes above this are almost certainly a typo — 3,600 means 60 hours on one
# ticket. Kept and flagged rather than dropped: deleting loses information,
# averaging loses the truth.
SUSPECT_OVER = 600

FIELDS = ("summary,created,updated,resolutiondate,resolution,priority,status,assignee,"
          "issuetype,duedate,customfield_10526,customfield_10230,customfield_10235,"
          "customfield_10233,customfield_10225,customfield_10521,customfield_10240,"
          # [CHART] Time in Status and Resolution SLA. Jira computes both; the
          # alternative is replaying every changelog ourselves.
          "customfield_10013,customfield_10530")

# `customfield_10529` (Time Taken to Resolve) and `customfield_10522` (Resolved
# On) look like they'd serve here and don't: 10529 returns negative values
# (-15058 on TCE-9120) and 10522 disagrees with `resolutiondate` by a month on
# the same issue. `resolutiondate` is the only timestamp that holds up.
# Native `worklog`/`timespent` is empty on all 1,200 issues — effort exists
# only in customfield_10526.

# Jira spells people differently from us. Confirmed mapping, not guesswork.
ALIASES = {
    "shivendra": "Shivendra",
    "shruti.jain": "Shruti Jain",
    "Niharika Kanakala": "Niharika K",
    "Vishal Reddy": "Vishal",
    "Yogesh Thakur": "Yogesh",
    "Archita Bhanja": "Archita",
    "sai.revanth": "sai.revanth",
    "Santhosh": "Santhosh",
    "Sreejith PV": "Sreejith PV",
}
# Present in Jira, wanted in ContentOps, no row yet.
CREATE_MEMBERS = ["Arpit Gupta", "Nishu Kumari", "Sreejith PV"]

# Jira lets an issue sit unassigned. Dropping those loses real effort from every
# total, so they land here and stay visible as work nobody owns.
UNASSIGNED = "Unassigned"

# Jira's status vocabulary -> ours.
STATUS_MAP = {
    "to do": "open", "open": "open", "backlog": "open",
    "in progress": "in_progress", "review": "in_progress",
    "blocked": "blocked", "on hold": "blocked",
    "done": "closed", "closed": "closed", "resolved": "closed",
    "invalid request": "closed",
}


def _auth() -> dict:
    token = base64.b64encode(
        f"{settings.JIRA_EMAIL}:{settings.JIRA_API_TOKEN}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _val(raw):
    if raw is None:
        return None
    if isinstance(raw, list):
        return next((v.get("value") or v.get("name") for v in raw if isinstance(v, dict)), None)
    if isinstance(raw, dict):
        return raw.get("value") or raw.get("name")
    return raw


def _vals(raw) -> list[str]:
    """Question type is Jira's only multi-select field here — every other
    caller of `_val` wants just the first value, this one wants all of them."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [v.get("value") or v.get("name") for v in raw
                if isinstance(v, dict) and (v.get("value") or v.get("name"))]
    if isinstance(raw, dict):
        name = raw.get("value") or raw.get("name")
        return [name] if name else []
    return [raw]


def _dt(raw: str | None) -> datetime | None:
    return datetime.fromisoformat(raw) if raw else None


def _naive(value: datetime | None) -> datetime | None:
    """Jira sends tz-aware timestamps; the columns are naive. Compare in UTC so
    a resolution never lands before its own creation on a timezone boundary."""
    if value is None:
        return None
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _time_in_status(raw: str | None, names: dict[str, str]) -> dict[str, int] | None:
    """Decode `statusId_*:*_count_*:*_millis_*|*_...` into {status: ms}.

    Verified against TCE-9216: 51m + 27m = 78m, versus 79m actual elapsed.
    Unknown ids keep their number rather than being dropped — a status renamed
    in Jira should show up as odd, not vanish.
    """
    if not raw:
        return None
    out: dict[str, int] = {}
    for part in raw.split("_*|*_"):
        bits = part.split("_*:*_")
        if len(bits) != 3:
            continue
        sid, _count, ms = bits
        if not ms.lstrip("-").isdigit():
            continue
        out[names.get(sid, f"status:{sid}")] = out.get(names.get(sid, f"status:{sid}"), 0) + int(ms)
    return out or None


async def _status_names(c: httpx.AsyncClient) -> dict[str, str]:
    r = await c.get("/rest/api/3/status")
    return {s["id"]: s["name"] for s in r.json()} if r.status_code < 400 else {}


async def fetch(frm: date, since: datetime | None = None) -> tuple[list[dict], dict[str, str]]:
    """TCE issues since `frm`, narrowed to those touched since `since`. GET only.

    Filtering on `updated` rather than `created` is what makes this usable as a
    frequent incremental: an issue created in May and edited yesterday is
    indistinguishable from an untouched one under a created-only filter, so
    every run re-read all 1,200 rows to find the ~15 that had changed — and
    reassignments and edited effort values drifted for as long as the run
    interval. `frm` stays as a floor so pre-May history never enters.
    """
    out: list[dict] = []
    token = None
    jql = f'project = TCE AND created >= "{frm.isoformat()}"'
    if since is not None:
        # Jira's JQL clock is minute-resolution; round down so an issue updated
        # inside the same minute as the last run isn't skipped.
        jql += f' AND updated >= "{since.strftime("%Y-%m-%d %H:%M")}"'
    jql += " ORDER BY created ASC"

    async with httpx.AsyncClient(
        base_url=settings.JIRA_BASE_URL, headers=_auth(), timeout=90
    ) as c:
        names = await _status_names(c)
        while True:
            params = {"jql": jql, "maxResults": 100, "fields": FIELDS}
            if token:
                params["nextPageToken"] = token
            r = await c.get("/rest/api/3/search/jql", params=params)
            if r.status_code >= 400:
                raise RuntimeError(f"Jira search failed: HTTP {r.status_code} {r.text[:200]}")
            body = r.json()
            out += body.get("issues", [])
            token = body.get("nextPageToken")
            if body.get("isLast") or not token:
                return out, names


async def resolve_people(db, names: set[str], create_missing: bool) -> dict[str, int]:
    """Jira display name -> member id, via the alias table."""
    by_name = {
        n.strip().lower(): i
        for n, i in await db.execute(select(Member.display_name, Member.id))
    }
    aliases = {
        a.strip().lower(): m
        for a, m in await db.execute(select(MemberAlias.alias, MemberAlias.member_id))
    }

    for alias, target in ALIASES.items():
        if alias.lower() in aliases:
            continue
        if (member_id := by_name.get(target.strip().lower())) is not None:
            db.add(MemberAlias(alias=alias, member_id=member_id))
            aliases[alias.lower()] = member_id

    for name in [*CREATE_MEMBERS, UNASSIGNED]:
        if name.strip().lower() not in by_name:
            m = Member(display_name=name, role="content")
            db.add(m)
            await db.flush()
            by_name[name.strip().lower()] = m.id
    await db.flush()

    resolved, unmatched = {}, []
    for name in names:
        key = name.strip().lower()
        if (mid := aliases.get(key) or by_name.get(key)) is not None:
            resolved[name] = mid
        elif create_missing:
            m = Member(display_name=name, role="content", is_active=False)
            db.add(m)
            await db.flush()
            resolved[name] = by_name[key] = m.id
            print(f"  + inactive member from Jira: {name!r}")
        else:
            unmatched.append(name)
    if unmatched:
        print(f"  unmatched assignees (skipped): {sorted(unmatched)}")
    return resolved


async def _lookup(db, model, name: str | None, cache: dict) -> int | None:
    if not (name := (name or "").strip()) or name.upper() == "NA":
        return None
    if name not in cache:
        row = model(name=name, sort_order=900)
        db.add(row)
        await db.flush()
        cache[name] = row.id
        print(f"  + {model.__tablename__}: {name!r}")
    return cache[name]


def _apply(item, f: dict, status: str, jira_status: str, names: dict) -> None:
    """Every field Jira owns, written onto the item.

    Shared by the insert and the refresh paths deliberately. They used to set
    overlapping-but-different subsets, which is how effort stayed stale on
    already-imported rows while looking correct on new ones.
    """
    eff = f.get("customfield_10526")
    minutes = int(eff) if eff is not None else None
    item.effort_minutes = minutes
    item.effort_suspect = bool(minutes and minutes > SUSPECT_OVER)
    item.request_type = _val(f.get("customfield_10240"))
    item.external_issue_type = f["issuetype"]["name"].strip()
    item.external_status = jira_status
    item.status = status
    item.customer = _val(f.get("customfield_10225")) or None
    item.pipeline = pipeline_for(f["issuetype"]["name"])
    item.notes = (f.get("summary") or "")[:2000] or None
    item.due_at = date.fromisoformat(f["duedate"]) if f.get("duedate") else None
    item.external_created_at = _naive(_dt(f.get("created")))
    item.resolved_at = _naive(_dt(f.get("resolutiondate")))
    item.resolution = _val(f.get("resolution"))
    item.priority = _val(f.get("priority"))
    sla = _val(f.get("customfield_10530"))
    item.sla_met = None if sla is None else (sla.strip().lower() == "met")
    item.time_in_status = _time_in_status(f.get("customfield_10013"), names)


async def _entry_for(db, entries: dict, member_id: int, on: date, stats) -> int:
    """The synthetic plan entry holding `member_id`'s issues for `on`."""
    entry_id = entries.get((member_id, on))
    if entry_id is None:
        entry = DailyEntry(
            member_id=member_id, entry_date=on, kind="plan", source="jira",
            idempotency_key=f"jira:{member_id}:{on.isoformat()}",
        )
        db.add(entry)
        await db.flush()
        entries[(member_id, on)] = entry_id = entry.id
        stats["entries_created"] += 1
    return entry_id


async def run(frm: date, dry_run: bool, create_missing: bool,
              refresh: bool = False, incremental: bool = False) -> dict:
    started = datetime.now(UTC).replace(tzinfo=None)
    since = None
    if incremental:
        async with Session() as db:
            cursor = await db.get(SyncCursor, CURSOR)
        if cursor is not None and cursor.last_synced_at is not None:
            # Overlap the window. Jira's `updated` is minute-resolution and a
            # run takes time, so an issue edited mid-run would otherwise fall
            # into the gap between "fetched" and "cursor written".
            since = _naive(cursor.last_synced_at) - timedelta(minutes=10)

    issues, status_names = await fetch(frm, since)
    print(f"fetched {len(issues)} issues since {frm}"
          + (f", updated since {since:%Y-%m-%d %H:%M}" if since else ""))

    by_type = collections.Counter(i["fields"]["issuetype"]["name"] for i in issues)
    print("  " + ", ".join(f"{k}={v}" for k, v in by_type.most_common()))

    async with Session() as db:
        names = {
            (i["fields"].get("assignee") or {}).get("displayName") or UNASSIGNED
            for i in issues
        }
        people = await resolve_people(db, names, create_missing)

        task_cache = {n: i for n, i in await db.execute(select(TaskType.name, TaskType.id))}
        question_cache = {n: i for n, i in await db.execute(select(QuestionType.name, QuestionType.id))}
        other_id = task_cache.get("Others") or task_cache.get("Other")

        seen = {
            k for (k,) in await db.execute(
                select(EntryItem.jira_issue_key).where(EntryItem.jira_issue_key.isnot(None))
            )
        }
        # One synthetic plan per member per day holds that day's issues.
        entries = {
            (m, d): i
            for m, d, i in await db.execute(
                select(DailyEntry.member_id, DailyEntry.entry_date, DailyEntry.id)
                .where(DailyEntry.kind == "plan")
            )
        }

        stats = collections.Counter()
        for issue in issues:
            f = issue["fields"]
            key = issue["key"]
            jira_status = _val(f.get("status")) or "To Do"
            status = STATUS_MAP.get(jira_status.strip().lower(), "open")

            who = (f.get("assignee") or {}).get("displayName")
            if who is None:
                # Unassigned work still happened; park it on a placeholder member
                # rather than dropping it silently from every total.
                who = UNASSIGNED
            if who not in people:
                stats["skipped_no_member"] += 1
                continue
            member_id = people[who]
            on = _naive(_dt(f["created"])).date()

            if key in seen:
                # --refresh re-reads what Jira may have changed since import,
                # rather than forcing a wipe and full reload.
                if refresh and not dry_run:
                    item = await db.scalar(
                        select(EntryItem).where(EntryItem.jira_issue_key == key)
                    )
                    if item is not None:
                        _apply(item, f, status, jira_status, status_names)
                        # Reassignment in Jira used to leave the item filed
                        # under the original assignee forever: refresh updated
                        # effort and status but never which member's entry the
                        # row hung off. That is why 11 of Shruti's tickets and
                        # 5 of Shivendra's sat on the wrong person while their
                        # effort totals matched Jira exactly.
                        entry = await db.get(DailyEntry, item.entry_id)
                        if entry is not None and entry.member_id != member_id:
                            item.entry_id = await _entry_for(
                                db, entries, member_id, entry.entry_date, stats
                            )
                            stats["reassigned"] += 1
                        stats["refreshed"] += 1
                else:
                    stats["already_present"] += 1
                continue

            effort = f.get("customfield_10526")
            minutes = int(effort) if effort is not None else None

            if dry_run:
                stats["would_import"] += 1
                if minutes and minutes > SUSPECT_OVER:
                    stats["suspect_effort"] += 1
                continue

            entry_id = await _entry_for(db, entries, member_id, on, stats)
            item = EntryItem(
                entry_id=entry_id,
                task_type_id=await _lookup(db, TaskType, _val(f.get("customfield_10230")),
                                           task_cache) or other_id,
                count=f.get("customfield_10233") and int(f["customfield_10233"]) or None,
                jira_issue_key=key,
                jira_issue_url=f"{settings.JIRA_BASE_URL}/browse/{key}",
                jira_state="ok",
            )
            _apply(item, f, status, jira_status, status_names)
            db.add(item)
            await db.flush()
            question_type_ids = [
                await _lookup(db, QuestionType, name, question_cache)
                for name in _vals(f.get("customfield_10235"))
            ]
            if question_type_ids:
                await db.execute(entry_item_question_types.insert(), [
                    {"entry_item_id": item.id, "question_type_id": qid}
                    for qid in question_type_ids
                ])
            db.add(EntryItemStatusEvent(
                entry_item_id=item.id, to_status=status, source="jira",
                changed_at=_naive(_dt(f.get("resolutiondate")) or _dt(f["created"])),
            ))
            stats["imported"] += 1
            if item.effort_suspect:
                stats["suspect_effort"] += 1

        if not dry_run:
            # Stamped with when the fetch *started*, not when it finished —
            # anything edited while the run was in flight is then inside the
            # next window rather than skipped over.
            row = await db.get(SyncCursor, CURSOR)
            if row is None:
                db.add(SyncCursor(key=CURSOR, last_synced_at=started, last_status="ok"))
            else:
                row.last_synced_at, row.last_status, row.last_error = started, "ok", None
            await db.commit()
        else:
            await db.rollback()

    print("\n  " + "\n  ".join(f"{k}: {v}" for k, v in sorted(stats.items())))
    return dict(stats)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default=DEFAULT_FROM.isoformat())
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would happen, write nothing")
    ap.add_argument("--refresh", action="store_true",
                    help="update already-imported rows with newly captured fields")
    ap.add_argument("--create-missing-members", action="store_true",
                    help="unknown Jira assignees become inactive members instead of skipping")
    ap.add_argument("--incremental", action="store_true",
                    help="only fetch issues updated since the last run")
    args = ap.parse_args()
    await run(date.fromisoformat(args.frm), args.dry_run,
              args.create_missing_members, args.refresh, args.incremental)


if __name__ == "__main__":
    asyncio.run(main())
