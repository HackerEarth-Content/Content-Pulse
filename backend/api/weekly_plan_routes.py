from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.deps import LEADS, Viewer, get_viewer, require_role
from core.users import current_user
from schemas.weekly_plan import (
    WeeklyPlanCompletionOut,
    WeeklyPlanItemIn,
    WeeklyPlanItemOut,
    WeeklyPlanItemPatch,
)
from services import weekly_plan as svc

router = APIRouter(prefix="/api/weekly-plan", tags=["weekly-plan"],
                   dependencies=[Depends(current_user)])

leads_only = Depends(require_role(*LEADS))


def _target_member(viewer: Viewer, requested: int | None) -> int:
    """Everyone defaults to their own week; a lead may name someone else's."""
    target = viewer.scope(requested)
    if target is None:
        target = viewer.member.id if viewer.member else None
    if target is None:
        raise svc.err(403, "no_member", "Your account isn't linked to a team member.")
    return target


@router.get("", response_model=list[WeeklyPlanItemOut])
async def list_weekly_plan(
    week: date,
    member_id: int | None = None,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    target = _target_member(viewer, member_id)
    items = await svc.list_items(db, target, week)
    return [WeeklyPlanItemOut.of(i) for i in items]


@router.post("/items", response_model=WeeklyPlanItemOut, status_code=201)
async def create_weekly_plan_item(
    body: WeeklyPlanItemIn,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    # Always filed as yourself — a weekly plan is a self-report, not something
    # a lead files on someone else's behalf.
    if viewer.member is None:
        raise svc.err(403, "no_member", "Your account isn't linked to a team member.")
    item = await svc.create_item(db, viewer.member.id, body.week_start, body.action)
    return WeeklyPlanItemOut.of(item)


@router.patch("/items/{item_id}", response_model=WeeklyPlanItemOut)
async def patch_weekly_plan_item(
    item_id: int,
    body: WeeklyPlanItemPatch,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    # Visibility can extend to a lead; edit rights never do — only the row's
    # own member may change its status or record an achievement on it.
    if viewer.member is None:
        raise svc.err(403, "no_member", "Your account isn't linked to a team member.")
    item = await svc.patch_item(
        db, item_id, viewer.member.id, status=body.status, achievement=body.achievement,
    )
    return WeeklyPlanItemOut.of(item)


@router.get("/completion", response_model=WeeklyPlanCompletionOut, dependencies=[leads_only])
async def weekly_plan_completion(week: date, db: AsyncSession = Depends(get_session)):
    return await svc.completion(db, week)
