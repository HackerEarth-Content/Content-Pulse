from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.dates import resolve_range
from core.orm import SyncCursor
from core.users import current_user
from integrations import jira, slack
from services import content_requests as cr

router = APIRouter(prefix="/api", tags=["integrations"],
                   dependencies=[Depends(current_user)])


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
    return await cr.query(db, status=status, assignee=assignee, priority=priority,
                          issue_type=issue_type, frm=frm, to=to, q=q,
                          page=page, page_size=page_size)


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
        {"key": r.key, "last_synced_at": r.last_synced_at,
         "status": r.last_status, "error": r.last_error}
        for r in rows
    ]
