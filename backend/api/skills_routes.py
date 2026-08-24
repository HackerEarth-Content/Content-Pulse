from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.deps import ADMINS, Viewer, get_viewer, require_role
from core.users import current_user
from schemas.skills import (
    RatingsBulkIn,
    SkillGraphOut,
    SkillOut,
    WindowOut,
    WindowPatch,
)
from services import skills as svc

router = APIRouter(prefix="/api/skills", tags=["skills"], dependencies=[Depends(current_user)])

admin_only = Depends(require_role(*ADMINS))


@router.get("", response_model=list[SkillOut])
async def list_skills(db: AsyncSession = Depends(get_session)):
    return await svc.list_skills(db)


@router.get("/window", response_model=WindowOut)
async def get_window(db: AsyncSession = Depends(get_session)):
    return await svc.window_state(db)


@router.patch("/window", response_model=WindowOut, dependencies=[admin_only])
async def patch_window(body: WindowPatch, db: AsyncSession = Depends(get_session)):
    return await svc.set_window(
        db, open_weekdays=body.open_weekdays, excluded_member_ids=body.excluded_member_ids,
    )


@router.get("/ratings/me")
async def get_my_ratings(db: AsyncSession = Depends(get_session), viewer: Viewer = Depends(get_viewer)):
    if viewer.member is None:
        raise svc.err(403, "no_member", "Your account isn't linked to a team member.")
    return await svc.member_ratings(db, viewer.member.id)


@router.put("/ratings/me")
async def save_my_ratings(
    body: RatingsBulkIn,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    if viewer.member is None:
        raise svc.err(403, "no_member", "Your account isn't linked to a team member.")
    return await svc.upsert_ratings(
        db, viewer.member.id, [(r.skill_id, r.level) for r in body.ratings],
    )


@router.get("/graph", response_model=SkillGraphOut)
async def skill_graph(db: AsyncSession = Depends(get_session)):
    skills, members = await svc.team_matrix(db)
    return {"skills": skills, "members": members}
