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
from datetime import date, datetime

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
    TaskType,
    pipeline_for,
)

CURSOR = "jira_backfill"
DEFAULT_FROM = date(2026, 5, 4)

# Minutes above this are almost certainly a typo — 3,600 means 60 hours on one
# ticket. Kept and flagged rather than dropped: deleting loses information,
# averaging loses the truth.
SUSPECT_OVER = 600

FIELDS = ("summary,created,updated,resolutiondate,status,assignee,issuetype,duedate,"
          "customfield_10526,customfield_10230,customfield_10235,customfield_10233,"
          "customfield_10225,customfield_10521,customfield_10240")

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


def _dt(raw: str | None) -> datetime | None:
    return datetime.fromisoformat(raw) if raw else None


async def fetch(frm: date) -> list[dict]:
    """Every TCE issue since `frm`, all issue types. GET only."""
    out: list[dict] = []
    token = None
    jql = f'project = TCE AND created >= "{frm.isoformat()}" ORDER BY created ASC'
    async with httpx.AsyncClient(
        base_url=settings.JIRA_BASE_URL, headers=_auth(), timeout=90
    ) as c:
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
                return out


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


async def run(frm: date, dry_run: bool, create_missing: bool,
              refresh: bool = False) -> dict:
    issues = await fetch(frm)
    print(f"fetched {len(issues)} issues since {frm}")

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
            if key in seen:
                # --refresh re-reads fields that were added after the first
                # import, rather than forcing a wipe and full reload.
                if refresh:
                    item = await db.scalar(
                        select(EntryItem).where(EntryItem.jira_issue_key == key)
                    )
                    if item is not None:
                        eff = f.get("customfield_10526")
                        item.effort_minutes = int(eff) if eff is not None else None
                        item.effort_suspect = bool(eff and int(eff) > SUSPECT_OVER)
                        item.request_type = _val(f.get("customfield_10240"))
                        item.external_issue_type = f["issuetype"]["name"].strip()
                        item.external_status = jira_status
                        item.status = status
                        item.customer = _val(f.get("customfield_10225")) or None
                        stats["refreshed"] += 1
                else:
                    stats["already_present"] += 1
                continue

            member_id = people[who]
            on = _dt(f["created"]).date()
            effort = f.get("customfield_10526")
            minutes = int(effort) if effort is not None else None

            if dry_run:
                stats["would_import"] += 1
                if minutes and minutes > SUSPECT_OVER:
                    stats["suspect_effort"] += 1
                continue

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

            item = EntryItem(
                entry_id=entry_id,
                task_type_id=await _lookup(db, TaskType, _val(f.get("customfield_10230")),
                                           task_cache) or other_id,
                question_type_id=await _lookup(db, QuestionType,
                                               _val(f.get("customfield_10235")), question_cache),
                customer=(_val(f.get("customfield_10225")) or None),
                count=f.get("customfield_10233") and int(f["customfield_10233"]) or None,
                notes=(f.get("summary") or "")[:2000] or None,
                due_at=date.fromisoformat(f["duedate"]) if f.get("duedate") else None,
                status=status,
                external_status=jira_status,
                external_issue_type=f["issuetype"]["name"],
                request_type=_val(f.get("customfield_10240")),
                pipeline=pipeline_for(f["issuetype"]["name"]),
                effort_minutes=minutes,
                effort_suspect=bool(minutes and minutes > SUSPECT_OVER),
                jira_issue_key=key,
                jira_issue_url=f"{settings.JIRA_BASE_URL}/browse/{key}",
                jira_state="ok",
            )
            db.add(item)
            await db.flush()
            db.add(EntryItemStatusEvent(
                entry_item_id=item.id, to_status=status, source="jira",
                changed_at=_dt(f.get("resolutiondate")) or _dt(f["created"]),
            ))
            stats["imported"] += 1
            if item.effort_suspect:
                stats["suspect_effort"] += 1

        if not dry_run:
            await db.execute(
                select(SyncCursor).where(SyncCursor.key == CURSOR)
            )
            cursor = await db.get(SyncCursor, CURSOR)
            if cursor is None:
                db.add(SyncCursor(key=CURSOR, last_synced_at=func.now(), last_status="ok"))
            else:
                cursor.last_synced_at, cursor.last_status, cursor.last_error = (
                    datetime.now(), "ok", None,
                )
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
    args = ap.parse_args()
    await run(date.fromisoformat(args.frm), args.dry_run,
              args.create_missing_members, args.refresh)


if __name__ == "__main__":
    asyncio.run(main())
