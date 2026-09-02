"""Seed content_health_* with every calendar month from --from through the
current month, one Redash sync per month.

    uv run python -m scripts.backfill_content_health
    uv run python -m scripts.backfill_content_health --from 2026-05
    uv run python -m scripts.backfill_content_health --force   # re-sync every month anyway

This is a one-off historical seed — the scheduler's 15-day job
(core/scheduler.py) only ever re-syncs the *current* month going forward, the
same split as scripts.backfill_jira (DEFAULT_FROM) vs. its own 10-minute
incremental job. Runs months sequentially, not concurrently: each is already
many slow, sequential Redash queries (see services/content_health.py), and
there's nothing to gain from hammering Redash with several months at once.

Resumable: a month already synced (any content_health_snapshots row for it —
the write in services/content_health.sync is atomic, so a partial write can't
exist) is skipped by default, so re-running after an interrupted or
partially-failed run doesn't repeat 30-60 minutes of already-good months.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta

from core.database import Session
from core.dates import month_bounds, today
from core.orm import ContentHealthSnapshot
from services import content_health
from sqlalchemy import select

DEFAULT_FROM = date(2026, 5, 1)


def _months(frm: date, to: date) -> list[date]:
    """The first of every month from frm through to, inclusive."""
    months, cur = [], frm.replace(day=1)
    while cur <= to:
        months.append(cur)
        cur = (cur.replace(day=28) + timedelta(days=7)).replace(day=1)
    return months


async def _already_synced(period_from: date) -> bool:
    async with Session() as db:
        return (
            await db.scalar(
                select(ContentHealthSnapshot.id)
                .where(ContentHealthSnapshot.period_from == period_from)
                .limit(1)
            )
        ) is not None


async def run(frm: date, force: bool = False) -> dict:
    results = {}
    for month_start in _months(frm, today()):
        start, end = month_bounds(month_start)
        if not force and await _already_synced(start):
            print(f"Skipping {start} to {end} — already synced")
            results[start.isoformat()] = {"ok": True, "skipped": True}
            continue
        print(f"Syncing {start} to {end} …")
        result = await content_health.sync(start, end)
        results[start.isoformat()] = result
        print(f"  {result}")
    return results


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default=DEFAULT_FROM.isoformat())
    ap.add_argument(
        "--force", action="store_true", help="re-sync months that already have data"
    )
    args = ap.parse_args()
    await run(date.fromisoformat(args.frm), args.force)


if __name__ == "__main__":
    asyncio.run(main())
