from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.users import current_user
from services import content_issues as ci

router = APIRouter(
    prefix="/api", tags=["content-issues"], dependencies=[Depends(current_user)]
)


@router.get("/content-issues/overview")
async def content_issues_overview(
    frm: date = Query(..., alias="from"),
    to: date = Query(...),
    db: AsyncSession = Depends(get_session),
):
    return await ci.overview(db, frm, to)


@router.post("/content-issues/sync")
async def sync_content_issues(background: BackgroundTasks):
    """Same shape as the Content Health sync button — runs in the
    background since a full Jira page-through can take a while."""
    background.add_task(ci.sync, True)
    return {"started": True}
