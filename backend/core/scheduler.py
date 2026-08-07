"""In-process timers.

Only correct with a single server process — two workers means two schedulers
and duplicate Slack posts. Fine today (one uvicorn, no --workers); put the jobs
behind a Postgres advisory lock before scaling out.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.config import settings
from core.dates import TZ, today
from integrations import jira, slack
from services import content_requests

log = logging.getLogger(__name__)


async def _sync_content_requests() -> None:
    try:
        log.info("content_requests sync: %s", await content_requests.sync())
    except Exception:
        log.exception("content_requests sync failed")


async def _sync_jira_history() -> None:
    """Pull anything created or changed in Jira since the last run.

    Without this the import is a point-in-time snapshot: 12 new tickets and 3
    edited effort values had already drifted a day after the first load.
    Unknown assignees become inactive members rather than being dropped, so
    nothing silently vanishes from the totals.
    """
    from datetime import date

    from scripts.backfill_jira import DEFAULT_FROM, run

    try:
        result = await run(DEFAULT_FROM, dry_run=False, create_missing=True, refresh=True)
        log.info("jira history sync: %s", result)
    except Exception:
        log.exception("jira history sync failed")


async def _sweep_jira() -> None:
    try:
        if n := await jira.sweep_pending():
            log.info("retried %s stranded jira writes", n)
    except Exception:
        log.exception("jira sweep failed")


def _digest(kind: str):
    async def run() -> None:
        try:
            log.info("slack %s digest: %s", kind, await slack.post_digest(today(), kind))
        except Exception:
            log.exception("slack %s digest failed", kind)

    return run


def start() -> AsyncIOScheduler:
    s = AsyncIOScheduler(timezone=TZ)
    s.add_job(_sync_content_requests, IntervalTrigger(minutes=15),
              id="content_requests", max_instances=1, coalesce=True)
    s.add_job(_sweep_jira, IntervalTrigger(minutes=5),
              id="jira_sweep", max_instances=1, coalesce=True)
    # Overnight: a full pass is ~12 API calls, so cost is irrelevant and a
    # missed run just means the next one catches up.
    s.add_job(_sync_jira_history, CronTrigger(hour=2, minute=15),
              id="jira_history", max_instances=1, coalesce=True)
    if settings.SLACK_BOT_TOKEN:
        s.add_job(_digest("plan"), CronTrigger(hour=10, minute=30), id="digest_plan")
        s.add_job(_digest("update"), CronTrigger(hour=19, minute=30), id="digest_update")
    s.start()
    return s
