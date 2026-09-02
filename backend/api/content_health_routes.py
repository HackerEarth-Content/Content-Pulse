from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.users import current_user
from services import content_health as ch

router = APIRouter(
    prefix="/api", tags=["content-health"], dependencies=[Depends(current_user)]
)


@router.get("/content-health/overview")
async def content_health_overview(
    frm: date = Query(..., alias="from"),
    to: date = Query(...),
    db: AsyncSession = Depends(get_session),
):
    return await ch.usage_overview(db, frm, to)


@router.get("/content-health/coverage")
async def content_health_coverage(
    problem_type: str,
    frm: date = Query(..., alias="from"),
    to: date = Query(...),
    db: AsyncSession = Depends(get_session),
):
    return await ch.topic_breakdown(db, problem_type, frm, to)


@router.get("/content-health/companies")
async def content_health_companies(
    problem_type: str,
    frm: date = Query(..., alias="from"),
    to: date = Query(...),
    db: AsyncSession = Depends(get_session),
):
    return await ch.top_companies(db, problem_type, frm, to)


@router.post("/integrations/redash/sync")
async def sync_redash(
    background: BackgroundTasks,
    frm: date = Query(..., alias="from"),
    to: date = Query(...),
):
    """Kicks off in the background — a run can take a long time (many slow,
    sequential Redash queries), so that's expected, not a timeout to chase.
    Poll /api/meta/sync-status for the result, same as the Jira sync."""
    background.add_task(ch.sync, frm, to)
    return {"started": True}
