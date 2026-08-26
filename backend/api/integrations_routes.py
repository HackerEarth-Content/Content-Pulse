import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_session
from core.dates import today
from core.deps import ADMINS, require_role
from core.orm import SyncCursor
from core.users import current_user
from integrations import jira, slack
from services import content_requests as cr

log = logging.getLogger(__name__)

admin_only = Depends(require_role(*ADMINS))

router = APIRouter(
    prefix="/api", tags=["integrations"], dependencies=[Depends(current_user)]
)


@router.get("/content-requests")
async def list_content_requests(
    status: str | None = None,
    assignee: str | None = None,
    priority: str | None = None,
    issue_type: str | None = None,
    frm: date | None = Query(None, alias="from"),
    to: date | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
):
    return await cr.query(
        db,
        status=status,
        assignee=assignee,
        priority=priority,
        issue_type=issue_type,
        frm=frm,
        to=to,
        q=q,
        page=page,
        page_size=page_size,
    )


@router.get("/content-requests/filters")
async def content_request_filters(db: AsyncSession = Depends(get_session)):
    return await cr.facets(db)


@router.get("/content-requests/stats")
async def content_request_stats(
    frm: date | None = Query(None, alias="from"),
    to: date | None = None,
    db: AsyncSession = Depends(get_session),
):
    return await cr.stats(db, frm, to)


@router.post("/content-requests/sync")
async def sync_content_requests():
    """On-demand version of the scheduled sync. Always calls Jira, even after an
    auth failure parked the timer — this is how you retry a fixed token."""
    return await cr.sync(force=True)


class DigestIn(BaseModel):
    kind: str
    on: date | None = None
    dry_run: bool = False


@router.post("/integrations/slack/digest")
async def slack_digest(data: DigestIn):
    """Replaces `manage.py post_slack_daily`."""
    from core.dates import today

    return await slack.post_digest(data.on or today(), data.kind, data.dry_run)


class RollCallIn(BaseModel):
    phase: str
    on: date | None = None


@router.post("/integrations/slack/roll-call", dependencies=[admin_only])
async def slack_roll_call(data: RollCallIn):
    """On-demand version of the 11:05/19:35 cron jobs — post the roster's
    plan/update status right now, regardless of the schedule."""
    return await slack.post_roll_call(data.on or today(), data.phase)


@router.post("/integrations/email/plan-reminder")
async def send_plan_reminder(
    dry_run: bool = True, db: AsyncSession = Depends(get_session)
):
    """Who would be nudged, and optionally do it now rather than waiting for 11am.
    Defaults to a dry run — sending mail is not something to do by accident."""
    from integrations import email as mail
    from services.entries import members_without_a_plan

    people = await members_without_a_plan(db, today())
    if dry_run:
        return {
            "dry_run": True,
            "would_email": [m.display_name for m in people],
            "enabled": settings.EMAIL_ENABLED,
        }
    return await mail.send_plan_reminders(people, f"{settings.FRONTEND_URL}/my-day")


@router.get("/integrations/jira/health")
async def jira_health(db: AsyncSession = Depends(get_session)):
    """Config + credential check. Never writes."""
    try:
        cfg = await jira.config(db)
    except jira.JiraDisabled as e:
        return {"ok": False, "reason": str(e)}
    async with jira._client() as c:
        r = await c.get("/rest/api/3/myself")
    return {
        "ok": r.status_code < 400,
        "project_key": cfg["project_key"],
        "issue_type": cfg["issue_type"],
        "account": r.json().get("displayName") if r.status_code < 400 else None,
        "error": None if r.status_code < 400 else jira._explain(r),
    }


@router.post("/integrations/jira/retry-pending")
async def retry_pending():
    return {"retried": await jira.sweep_pending()}


@router.get("/meta/sync-status")
async def sync_status(db: AsyncSession = Depends(get_session)):
    rows = await db.scalars(select(SyncCursor))
    return [
        {
            "key": r.key,
            "last_synced_at": r.last_synced_at,
            "status": r.last_status,
            "error": r.last_error,
        }
        for r in rows
    ]


# Opening the dashboard triggers a sync, so this is called once per session by
# every person who signs in — and they tend to arrive at the same time each
# morning. Two guards keep that from turning into a burst of Jira traffic:
# nothing runs if a sync is already in flight, and nothing runs if one finished
# within the cooldown. Ten people opening the app at 09:30 cost one API call.
_SYNC_COOLDOWN = timedelta(minutes=5)
_sync_lock = asyncio.Lock()
_sync_state: dict = {"last_run": None, "last_result": None, "last_error": None}


async def _sync_history() -> None:
    """Pull anything created or changed in Jira since the last run.

    Reads Jira, writes only our own database — no Jira write is ever issued
    from here. Exceptions are recorded rather than raised: this runs as a
    background task, where an exception would vanish into the log with nothing
    to show in the UI.
    """
    from scripts.backfill_jira import DEFAULT_FROM, run

    async with _sync_lock:
        # Re-check the cooldown now that we hold the lock. The route checks it
        # too, but background tasks start *after* the response is sent, so
        # several concurrent requests can all pass that check before any of them
        # acquires the lock — and would then queue up and each run a redundant
        # pass. The check that counts is this one.
        last = _sync_state["last_run"]
        if last and datetime.now(UTC) - last < _SYNC_COOLDOWN:
            log.debug(
                "jira history sync skipped; ran %ss ago",
                int((datetime.now(UTC) - last).total_seconds()),
            )
            return
        try:
            _sync_state["last_result"] = await run(
                DEFAULT_FROM,
                dry_run=False,
                create_missing=True,
                refresh=True,
                incremental=True,
            )
            _sync_state["last_error"] = None
        except Exception as e:
            _sync_state["last_error"] = str(e)[:500]
            log.exception("jira history sync failed")
        finally:
            _sync_state["last_run"] = datetime.now(UTC)


@router.post("/integrations/jira/sync")
async def sync_jira_history(background: BackgroundTasks, force: bool = False):
    """Refresh ticket and effort data from Jira. Called when the dashboard opens.

    Returns immediately — a first pass reads ~1,200 issues and would time out the
    request. Poll `/api/meta/sync-status` for the result.
    """
    last = _sync_state["last_run"]
    if _sync_lock.locked():
        return {"started": False, "reason": "a sync is already running"}
    if not force and last and datetime.now(UTC) - last < _SYNC_COOLDOWN:
        age = int((datetime.now(UTC) - last).total_seconds())
        return {
            "started": False,
            "reason": f"synced {age}s ago",
            "cooldown_seconds": int(_SYNC_COOLDOWN.total_seconds()),
        }

    background.add_task(_sync_history)
    return {"started": True}
