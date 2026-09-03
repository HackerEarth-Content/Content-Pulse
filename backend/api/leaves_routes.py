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


def _member_required(viewer: Viewer, member_id: int | None) -> int:
    """Self for anyone; a lead may name another member instead."""
    if member_id is not None:
        return viewer.writer_id(member_id)
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
    member_id: int | None = None,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    return {"dates": await svc.list_leaves(db, _member_required(viewer, member_id))}


@router.post("", response_model=LeaveOut)
async def mark_leave(
    body: LeaveDatesIn,
    member_id: int | None = None,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    dates = await svc.add_leave_dates(
        db, _member_required(viewer, member_id), body.dates
    )
    return {"dates": dates}


@router.delete("/{on}", response_model=LeaveOut)
async def unmark_leave(
    on: date,
    member_id: int | None = None,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    dates = await svc.remove_leave_date(db, _member_required(viewer, member_id), on)
    return {"dates": dates}
