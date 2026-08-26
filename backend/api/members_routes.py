from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.dates import resolve_range
from core.deps import ADMINS, Viewer, get_viewer, require_role
from core.orm import DailyEntry, Member, PIPELINES, QuestionType, TaskType
from core.users import current_user
from schemas.entries import (
    LookupIn,
    LookupOut,
    LookupPatch,
    MemberIn,
    MemberOut,
    MemberPatch,
)
from services import analytics as an
from services.entries import err

router = APIRouter(
    prefix="/api", tags=["members"], dependencies=[Depends(current_user)]
)

# Real role gating. SUPERADMIN_EMAILS short-circuits it inside require_role, so
# the screen used to grant roles is never locked behind having one.
admin_only = Depends(require_role(*ADMINS))


@router.get("/members", response_model=list[MemberOut])
async def list_members(
    role: str | None = None,
    is_active: bool | None = Query(True),
    q: str | None = None,
    db: AsyncSession = Depends(get_session),
):
    where = []
    if role:
        where.append(Member.role == role)
    if is_active is not None:
        where.append(Member.is_active == is_active)
    if q:
        where.append(Member.display_name.ilike(f"%{q}%"))
    return list(
        await db.scalars(select(Member).where(*where).order_by(Member.display_name))
    )


@router.post(
    "/members", response_model=MemberOut, status_code=201, dependencies=[admin_only]
)
async def create_member(data: MemberIn, db: AsyncSession = Depends(get_session)):
    if await db.scalar(
        select(Member).where(
            func.lower(func.trim(Member.display_name))
            == data.display_name.strip().lower()
        )
    ):
        raise err(409, "member_exists", "A member with that name already exists.")
    member = Member(**data.model_dump())
    db.add(member)
    await db.commit()
    return member


@router.patch(
    "/members/{member_id}", response_model=MemberOut, dependencies=[admin_only]
)
async def patch_member(
    member_id: int, patch: MemberPatch, db: AsyncSession = Depends(get_session)
):
    member = await db.get(Member, member_id)
    if member is None:
        raise err(404, "not_found", "No such member.")
    for field, value in patch.model_dump(exclude_unset=True).items():
        setattr(member, field, value)
    await db.commit()
    return member


@router.delete("/members/{member_id}", dependencies=[admin_only])
async def remove_member(member_id: int, db: AsyncSession = Depends(get_session)):
    """Delete outright if they never logged anything; otherwise revoke access and
    keep the history. Reports which happened — a bare 204 left the caller unable
    to tell why the person was still on the list."""
    member = await db.get(Member, member_id)
    if member is None:
        raise err(404, "not_found", "No such member.")

    entries = await db.scalar(
        select(func.count())
        .select_from(DailyEntry)
        .where(DailyEntry.member_id == member_id)
    )
    if entries:
        member.is_active = False
        await db.commit()
        return {
            "deleted": False,
            "entries": entries,
            "detail": f"{member.display_name} has {entries} logged "
            f"{'entry' if entries == 1 else 'entries'}, so their history was kept "
            "and their access revoked.",
        }

    name = member.display_name
    await db.delete(member)
    await db.commit()
    return {"deleted": True, "entries": 0, "detail": f"{name} was removed."}


@router.get("/members/{member_id}/profile")
async def member_profile(
    member_id: int,
    period: str | None = None,
    frm: date | None = Query(None, alias="from"),
    to: date | None = None,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    """Everything about one person in a single call: totals across every
    pipeline, then the split by stream, work area, question type and customer.

    One request rather than eight, because the page shows them together and a
    half-loaded profile reads as wrong numbers rather than as loading.
    """
    if not viewer.may_write_for(member_id):
        raise err(404, "not_found", "No such member.")
    member = await db.get(Member, member_id)
    if member is None:
        raise err(404, "not_found", "No such member.")

    start, end = resolve_range(period, frm, to)
    mine = an.Scope(frm=start, to=end, member_id=member_id)
    team = an.Scope(frm=start, to=end)

    totals, team_totals = await an.summary(db, mine), await an.summary(db, team)
    return {
        "member": {
            "id": member.id,
            "display_name": member.display_name,
            "role": member.role,
            "email": member.email,
        },
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        # Unified: every pipeline folded into one set of headline numbers.
        "totals": totals,
        "share_of_team": {
            "tasks": round(totals["tasks"] / team_totals["tasks"], 4)
            if team_totals["tasks"]
            else None,
            "effort": round(totals["effort_minutes"] / team_totals["effort_minutes"], 4)
            if team_totals["effort_minutes"]
            else None,
        },
        "by_pipeline": await an.by_pipeline(db, mine),
        "by_task_type": await an.by_task_type(db, mine),
        "by_question_type": await an.by_question_type(db, mine),
        "by_customer": await an.by_customer(db, mine, limit=25),
        # Where their minutes went, and how the work was rated — the two things
        # a per-person page was missing to be worth opening.
        "effort_breakdown": await an.effort_breakdown(db, mine),
        "by_area": await an.by_area(db, mine),
        "quality": await an.quality_mix(db, mine),
        "cycle_time": await an.cycle_time(db, mine),
        "adherence": (await an.plan_adherence(db, mine) or [None])[0],
        "trend": await an.trend(db, mine),
    }


LOOKUPS = {"task-types": TaskType, "question-types": QuestionType}


def _model(kind: str):
    if (model := LOOKUPS.get(kind)) is None:
        raise err(404, "unknown_lookup", f"No lookup called {kind!r}.")
    return model


# The only two pipelines this form has ever reliably created — the rest
# either have no Task Type field in Jira at all, or an issue-type name Jira
# itself stores with stray whitespace, unverified against a live create.
CREATABLE_WORK_TYPES = ("Content Tasks", "Content Requests")


@router.get("/meta/work-types")
async def list_work_types():
    return [{"key": PIPELINES[name], "label": name} for name in CREATABLE_WORK_TYPES]


@router.get("/meta/lookups/{kind}", response_model=list[LookupOut])
async def list_lookups(
    kind: str, include_inactive: bool = False, db: AsyncSession = Depends(get_session)
):
    model = _model(kind)
    where = [] if include_inactive else [model.is_active.is_(True)]
    return list(
        await db.scalars(
            select(model).where(*where).order_by(model.sort_order, model.name)
        )
    )


@router.post(
    "/meta/lookups/{kind}",
    response_model=LookupOut,
    status_code=201,
    dependencies=[admin_only],
)
async def create_lookup(
    kind: str, body: LookupIn, db: AsyncSession = Depends(get_session)
):
    model = _model(kind)
    name = body.name.strip()
    if await db.scalar(select(model).where(func.lower(model.name) == name.lower())):
        raise err(409, "lookup_exists", f"{name!r} already exists.")
    row = model(name=name, sort_order=body.sort_order)
    db.add(row)
    await db.commit()
    return row


@router.patch(
    "/meta/lookups/{kind}/{lookup_id}",
    response_model=LookupOut,
    dependencies=[admin_only],
)
async def patch_lookup(
    kind: str,
    lookup_id: int,
    body: LookupPatch,
    db: AsyncSession = Depends(get_session),
):
    """Rename or retire. Retiring keeps history intact — the value stops being
    offered on forms but every task already using it still reads correctly."""
    row = await db.get(_model(kind), lookup_id)
    if row is None:
        raise err(404, "not_found", "No such lookup value.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await db.commit()
    return row
