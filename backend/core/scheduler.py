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
from core.dates import TZ, month_bounds, today, week_bounds
from integrations import email, jira, slack
from services import content_health, content_issues, content_requests

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

    from scripts.backfill_jira import DEFAULT_FROM, run

    try:
        result = await run(
            DEFAULT_FROM,
            dry_run=False,
            create_missing=True,
            refresh=True,
            incremental=True,
        )
        log.info("jira history sync: %s", result)
    except Exception:
        log.exception("jira history sync failed")


async def _mark_jira_deletions() -> None:
    """Catches the one thing the incremental sync above structurally can't:
    an issue Jira no longer returns emits no `updated` event to catch."""
    from scripts.backfill_jira import DEFAULT_FROM
    from scripts.reconcile_jira import mark_missing

    try:
        log.info("jira deletion check: %s", await mark_missing(DEFAULT_FROM))
    except Exception:
        log.exception("jira deletion check failed")


async def _sync_content_health() -> None:
    """Refresh the current month's candidate-usage/coverage numbers from
    Redash. Slow (Redash queries can take minutes) and only reachable over
    VPN in practice, so a failure here is logged and skipped, not raised —
    same treatment as every other job in this file. A person can also force
    it from the Content Health tab (POST /api/integrations/redash/sync)."""
    try:
        frm, to = month_bounds(today())
        log.info("content health sync: %s", await content_health.sync(frm, to))
    except Exception:
        log.exception("content health sync failed")


async def _sync_content_issues() -> None:
    """Friday refresh of the Content Issue Analysis tab's data — a full
    re-mirror (see content_issues.sync's docstring), not incremental, so
    weekly is plenty; a person can also force it from the tab's sync button
    (POST /api/content-issues/sync)."""
    try:
        log.info("content issue sync: %s", await content_issues.sync(True))
    except Exception:
        log.exception("content issue sync failed")


async def _sweep_jira() -> None:
    try:
        if n := await jira.sweep_pending():
            log.info("retried %s stranded jira writes", n)
    except Exception:
        log.exception("jira sweep failed")


async def _publish_scheduled() -> None:
    """Release plans and updates whose scheduled time has come.

    Runs every minute: a plan set for 20:00 that goes out at 20:04 is a plan
    nobody trusts the schedule on. `posted_at` makes a re-run harmless, so a
    missed minute during a restart is caught by the next tick.
    """
    from core.database import Session
    from services.publish import publish_due

    try:
        async with Session() as db:
            if (result := await publish_due(db))["published"]:
                log.info("published scheduled entries: %s", result)
    except Exception:
        log.exception("scheduled publish failed")


async def _remind_to_plan() -> None:
    """Nudge anyone who hasn't filed a plan by PLAN_REMINDER_HOUR.

    Only people with an email and an active membership — and only real plans,
    so a backfilled Jira day never counts as having planned.
    """
    from core.database import Session
    from services.entries import members_without_a_plan

    try:
        async with Session() as db:
            people = await members_without_a_plan(db, today())
        if not people:
            log.info("plan reminder: everyone has planned")
            return
        result = await email.send_plan_reminders(
            people, f"{settings.FRONTEND_URL}/my-day"
        )
        log.info("plan reminder: %s", result)
    except Exception:
        log.exception("plan reminder failed")


def _digest(kind: str):
    async def run() -> None:
        try:
            log.info(
                "slack %s digest: %s", kind, await slack.post_digest(today(), kind)
            )
        except Exception:
            log.exception("slack %s digest failed", kind)

    return run


def _roll_call(phase: str):
    """Who's planned/updated today and who hasn't, posted as one summary
    message — distinct from `_digest`, which reposts individual entries."""

    async def run() -> None:
        try:
            log.info(
                "slack %s roll call: %s",
                phase,
                await slack.post_roll_call(today(), phase),
            )
        except Exception:
            log.exception("slack %s roll call failed", phase)

    return run


def _weekly_plan_status(phase: str):
    """Monday 11:59pm: who's filed this week's plan. Friday 11:59pm: who's
    updated it. `week_bounds` gives the Monday of whichever week `today()`
    falls in, which on these two days is always the week just being reported."""

    async def run() -> None:
        try:
            week_start, _ = week_bounds(today())
            log.info(
                "slack weekly plan %s: %s",
                phase,
                await slack.post_weekly_plan_status(week_start, phase),
            )
        except Exception:
            log.exception("slack weekly plan %s failed", phase)

    return run


def start() -> AsyncIOScheduler:
    s = AsyncIOScheduler(timezone=TZ)
    s.add_job(
        _sync_content_requests,
        IntervalTrigger(minutes=15),
        id="content_requests",
        max_instances=1,
        coalesce=True,
    )
    # Every 15 days, not 6 hours — a month's candidate-usage numbers don't
    # meaningfully change hour to hour, and a run can take a long time (many
    # slow Redash queries in sequence), so there's nothing to gain from a
    # tighter cadence. Historical months (before this job's first run) are
    # seeded once via `scripts.backfill_content_health`, not by this job.
    s.add_job(
        _sync_content_health,
        IntervalTrigger(days=15),
        id="content_health",
        max_instances=1,
        coalesce=True,
    )
    s.add_job(
        _sync_content_issues,
        CronTrigger(hour=18, minute=0, day_of_week="fri", timezone=TZ),
        id="content_issues",
        max_instances=1,
        coalesce=True,
    )
    s.add_job(
        _sweep_jira,
        IntervalTrigger(minutes=5),
        id="jira_sweep",
        max_instances=1,
        coalesce=True,
    )
    # Every 10 min, not nightly. The sync filters on `updated` now, so a quiet
    # window costs one API call instead of twelve — and nightly meant a
    # reassignment or an edited effort value stayed wrong for up to a day.
    s.add_job(
        _sync_jira_history,
        IntervalTrigger(minutes=10),
        id="jira_history",
        max_instances=1,
        coalesce=True,
    )
    # A full re-fetch, not incremental — a deletion emits no `updated` event,
    # so this is the only way that drift ever surfaces. Heavier, hence hourly.
    s.add_job(
        _mark_jira_deletions,
        IntervalTrigger(hours=2),
        id="jira_deletions",
        max_instances=1,
        coalesce=True,
    )
    s.add_job(
        _publish_scheduled,
        IntervalTrigger(minutes=1),
        id="publish_scheduled",
        max_instances=1,
        coalesce=True,
    )
    s.add_job(
        _remind_to_plan,
        CronTrigger(
            hour=settings.PLAN_REMINDER_HOUR,
            minute=0,
            day_of_week="mon-fri",
            timezone=TZ,
        ),
        id="plan_reminder",
        max_instances=1,
        coalesce=True,
    )
    if settings.SLACK_BOT_TOKEN:
        s.add_job(
            _digest("plan"),
            CronTrigger(hour=10, minute=30, timezone=TZ),
            id="digest_plan",
        )
        s.add_job(
            _digest("update"),
            CronTrigger(hour=19, minute=30, timezone=TZ),
            id="digest_update",
        )
        # Roll call: the whole roster's status in one message, Mon-Fri only —
        # unlike the digests above, weekends have nothing to chase anyone on.
        s.add_job(
            _roll_call("morning"),
            CronTrigger(hour=12, minute=0, day_of_week="mon-fri", timezone=TZ),
            id="plan_rollcall",
            max_instances=1,
            coalesce=True,
        )
        s.add_job(
            _roll_call("evening"),
            CronTrigger(hour=19, minute=35, day_of_week="mon-fri", timezone=TZ),
            id="update_rollcall",
            max_instances=1,
            coalesce=True,
        )
        # Same evening roll call, posted again late — catches anyone who logs
        # their update after the 19:35 check-in rather than before it.
        s.add_job(
            _roll_call("evening"),
            CronTrigger(hour=23, minute=55, day_of_week="mon-fri", timezone=TZ),
            id="update_rollcall_late",
            max_instances=1,
            coalesce=True,
        )
        s.add_job(
            _weekly_plan_status("monday"),
            CronTrigger(hour=23, minute=59, day_of_week="mon", timezone=TZ),
            id="weekly_plan_monday",
            max_instances=1,
            coalesce=True,
        )
        s.add_job(
            _weekly_plan_status("friday"),
            CronTrigger(hour=23, minute=59, day_of_week="fri", timezone=TZ),
            id="weekly_plan_friday",
            max_instances=1,
            coalesce=True,
        )
    s.start()
    return s
