"""Seed lookup tables, and optionally import the Django app's SQLite data.

    uv run python -m scripts.seed
    uv run python -m scripts.seed --import ../../contentops_ref/ContentOps/backend/db.sqlite3

Idempotent: safe to re-run. Everything keys off natural keys, not row ids.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import Session
from core.orm import (
    DailyEntry,
    EntryItem,
    EntryItemStatusEvent,
    Member,
    QuestionType,
    SlackDayThread,
    TaskType,
    entry_item_question_types,
)

TASK_TYPES = [
    "Internal meeting",
    "Assessment creation",
    "Content review",
    "Documentation",
    "Content creation and development",
    "Content refixing",
    "External meeting",
    "Content manual-audit",
    "Content feedback analysis",
    "Others",
]

QUESTION_TYPES = [
    "Programming", "SQL", "Frontend", "Full Stack", "Automation Testing",
    "DevOps", "Machine Learning", "Diagram", "Data Science", "File Upload",
    "Project", "Java Project", "C# Project", "Python Project", "Subjective",
    "Multiple Choice", "Approximate", "Golf", "RegExp", "FileEval",
]


async def _by_name(db: AsyncSession, model) -> dict[str, int]:
    rows = await db.execute(select(model.name, model.id))
    return {name: id_ for name, id_ in rows}


async def seed_lookups(db: AsyncSession) -> None:
    for model, names in ((TaskType, TASK_TYPES), (QuestionType, QUESTION_TYPES)):
        existing = await _by_name(db, model)
        db.add_all(
            model(name=n, sort_order=i)
            for i, n in enumerate(names)
            if n not in existing
        )

    await db.flush()
    print(f"lookups: {len(TASK_TYPES)} task types, "
          f"{len(QUESTION_TYPES)} question types")


async def _lookup_id(db: AsyncSession, model, name: str | None, cache: dict) -> int | None:
    """Resolve a free-text value to a lookup row, adding unknown ones as
    inactive — the old app stored these as plain strings, so history contains
    values that were never on any dropdown."""
    if not (name := (name or "").strip()):
        return None
    if name not in cache:
        row = model(name=name, is_active=False, sort_order=999)
        db.add(row)
        await db.flush()
        cache[name] = row.id
        print(f"  + inactive {model.__tablename__}: {name!r}")
    return cache[name]


def _as_date(v) -> date | None:
    return date.fromisoformat(v) if v else None


def _as_dt(v) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


async def import_sqlite(db: AsyncSession, path: str) -> None:
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    members = {name: id_ for name, id_ in await db.execute(select(Member.display_name, Member.id))}
    old_member = {}
    for r in src.execute("SELECT * FROM tracker_member"):
        if r["display_name"] not in members:
            m = Member(
                display_name=r["display_name"],
                slack_user_id=r["slack_user_id"],
                is_active=bool(r["is_active"]),
                role=r["role"] or "content",
            )
            db.add(m)
            await db.flush()
            members[r["display_name"]] = m.id
        old_member[r["id"]] = members[r["display_name"]]
    print(f"members: {len(old_member)}")

    task_cache = await _by_name(db, TaskType)
    question_cache = await _by_name(db, QuestionType)
    other_id = task_cache["Other"]

    # One plan per member per day is enforced now, and the source has three
    # plans for one member/date. Decide the survivor before inserting anything,
    # so the duplicates' items fold into it instead of being dropped.
    src_entries = list(src.execute("SELECT * FROM tracker_dailyentry ORDER BY id"))
    survivor, folded, first_plan = {}, {}, {}
    for r in src_entries:
        key = (r["member_id"], r["entry_date"])
        if r["kind"] == "plan" and key in first_plan:
            survivor[r["id"]] = first_plan[key]
            folded.setdefault(first_plan[key], []).append(r["id"])
        else:
            survivor[r["id"]] = r["id"]
            if r["kind"] == "plan":
                first_plan[key] = r["id"]

    # idempotency_key doubles as the "already imported" marker, so a re-run
    # skips these rows instead of tripping the one-plan-per-day constraint. A
    # survivor's key lists every source row folded into it: "import:7+11+12".
    seen: dict[int, int] = {}
    for k, entry_id in await db.execute(
        select(DailyEntry.idempotency_key, DailyEntry.id).where(
            DailyEntry.idempotency_key.startswith("import:")
        )
    ):
        seen.update({int(p): entry_id for p in k.removeprefix("import:").split("+")})

    old_entry, fresh = dict(seen), set()
    for r in src_entries:
        if r["id"] in seen or survivor[r["id"]] != r["id"]:
            continue
        e = DailyEntry(
            entry_date=_as_date(r["entry_date"]),
            kind=r["kind"],
            status=r["status"],
            member_id=old_member[r["member_id"]],
            raw_text=r["raw_text"],
            source="import",
            idempotency_key="import:" + "+".join(
                str(i) for i in [r["id"], *folded.get(r["id"], [])]
            ),
            slack_reply_ts=r["slack_reply_ts"],
        )
        db.add(e)
        await db.flush()
        fresh.add(r["id"])
        for old_id in [r["id"], *folded.get(r["id"], [])]:
            old_entry[old_id] = e.id
    print(f"entries: {len(fresh)} new, {len(set(seen.values()))} already present"
          + (f", {sum(len(v) for v in folded.values())} duplicate plans merged" if folded else ""))

    old_item = {}
    rows = src.execute("SELECT * FROM tracker_entryitem ORDER BY entry_id, id")
    for i, r in enumerate(x for x in rows if survivor[x["entry_id"]] in fresh):
        it = EntryItem(
            entry_id=old_entry[r["entry_id"]],
            task_type_id=await _lookup_id(db, TaskType, r["task_type"], task_cache) or other_id,
            customer=r["customer"],
            count=r["count"] or None,
            notes=r["notes"],
            due_at=_as_date(r["due_at"]),
            status=r["status"],
            sort_order=i,
            jira_issue_key=r["jira_issue_key"],
            jira_issue_url=r["jira_issue_url"],
            jira_state="ok" if r["jira_issue_key"] else "none",
        )
        db.add(it)
        await db.flush()
        if qt_id := await _lookup_id(db, QuestionType, r["question_type"], question_cache):
            await db.execute(entry_item_question_types.insert(),
                              [{"entry_item_id": it.id, "question_type_id": qt_id}])
        old_item[r["id"]] = it.id
        # No transition history exists upstream; one row so cycle-time queries
        # have a floor to measure from.
        db.add(EntryItemStatusEvent(entry_item_id=it.id, to_status=r["status"], source="import"))

    for r in src.execute("SELECT id, plan_item_id FROM tracker_entryitem WHERE plan_item_id IS NOT NULL"):
        if (new := old_item.get(r["plan_item_id"])) and (mine := old_item.get(r["id"])):
            (await db.get(EntryItem, mine)).plan_item_id = new
    print(f"items: {len(old_item)} new")

    threads = 0
    for r in src.execute("SELECT * FROM tracker_slackdaythread"):
        channel = r["channel"] or ""
        if await db.scalar(
            select(SlackDayThread.id).where(
                SlackDayThread.digest_date == _as_date(r["digest_date"]),
                SlackDayThread.kind == r["kind"],
                SlackDayThread.channel == channel,
            )
        ):
            continue
        db.add(SlackDayThread(
            digest_date=_as_date(r["digest_date"]),
            kind=r["kind"],
            channel=channel,
            parent_ts=r["parent_ts"],
        ))
        threads += 1
    print(f"slack threads: {threads}")
    src.close()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--import", dest="sqlite_path", help="path to the Django db.sqlite3")
    args = ap.parse_args()

    async with Session() as db:
        await seed_lookups(db)
        if args.sqlite_path:
            await import_sqlite(db, args.sqlite_path)
        await db.commit()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
