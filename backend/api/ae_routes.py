from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.dates import resolve_range
from core.deps import AE, Viewer, get_viewer, require_role
from core.orm import User
from core.users import current_user
from services import ae as svc
from services.entries import err

router = APIRouter(prefix="/api/ae", tags=["ae"], dependencies=[Depends(current_user)])


class AEUpsertIn(BaseModel):
    member_id: int
    entry_date: date
    notes: str = Field(min_length=1)
    metrics: dict[str, int] = {}
    # Echo back the updated_at you were shown; omit only when creating.
    version: datetime | None = None


@router.get("/metrics")
async def metrics(db: AsyncSession = Depends(get_session)):
    return [
        {"key": d.key, "label": d.name, "sort_order": d.sort_order}
        for d in await svc.metric_defs(db)
    ]


@router.get("/daily")
async def daily(
    period: str | None = None,
    frm: date | None = Query(None, alias="from"),
    to: date | None = None,
    member_id: int | None = None,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    frm, to = resolve_range(period, frm, to)
    rows = await svc.list_range(db, frm, to, viewer.scope(member_id))
    return {"range": {"from": frm.isoformat(), "to": to.isoformat()},
            "items": [svc.serialise(r) for r in rows]}


@router.get("/daily/{member_id}/{on}")
async def one(member_id: int, on: date, db: AsyncSession = Depends(get_session),
              viewer: Viewer = Depends(get_viewer)):
    row = await svc.get_one(db, member_id, on)
    if row is None or not viewer.may_write_for(row.member_id):
        raise err(404, "not_found", "Nothing logged for that member and date.")
    return svc.serialise(row)


@router.put("/daily")
async def upsert(data: AEUpsertIn, db: AsyncSession = Depends(get_session),
                 user: User = Depends(current_user),
                 viewer: Viewer = Depends(require_role(*AE))):
    row = await svc.upsert(
        db, member_id=viewer.writer_id(data.member_id), entry_date=data.entry_date, notes=data.notes,
        metrics=data.metrics, version=data.version, user_id=user.id,
    )
    return svc.serialise(row)
