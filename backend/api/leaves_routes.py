from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import services.leaves as svc
from core.database import get_session
from core.deps import Viewer, get_viewer
from core.users import current_user
from datetime import date
from schemas.leaves import LeaveDatesIn, LeaveOut

router = APIRouter(
    prefix="/api/leaves", tags=["leaves"], dependencies=[Depends(current_user)]
)


def _member_required(viewer: Viewer) -> int:
    if viewer.member is None:
        raise HTTPException(
            403,
            {
                "code": "no_member",
                "detail": "Your account isn't linked to a team member.",
            },
        )
    return viewer.member.id


@router.get("", response_model=LeaveOut)
async def my_leaves(
    db: AsyncSession = Depends(get_session), viewer: Viewer = Depends(get_viewer)
):
    return {"dates": await svc.list_leaves(db, _member_required(viewer))}


@router.post("", response_model=LeaveOut)
async def mark_leave(
    body: LeaveDatesIn,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    dates = await svc.add_leave_dates(db, _member_required(viewer), body.dates)
    return {"dates": dates}


@router.delete("/{on}", response_model=LeaveOut)
async def unmark_leave(
    on: date,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    dates = await svc.remove_leave_date(db, _member_required(viewer), on)
    return {"dates": dates}
