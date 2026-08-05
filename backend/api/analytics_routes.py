"""Thin passthroughs to services/analytics.py.

Responses are plain dicts rather than declared models — these are aggregate
shapes the SPA mirrors in types.ts, and a Pydantic model per endpoint would be
~200 lines that only restate the SQL.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.dates import resolve_range, today
from core.users import current_user
from services import analytics as an

router = APIRouter(prefix="/api/analytics", tags=["analytics"],
                   dependencies=[Depends(current_user)])


async def scope(
    period: str | None = None,
    frm: date | None = Query(None, alias="from"),
    to: date | None = None,
    member_id: int | None = None,
    task_type_id: int | None = None,
) -> an.Scope:
    start, end = resolve_range(period, frm, to)
    if start > end:
        from services.entries import err
        raise err(422, "bad_range", "`from` is after `to`.")
    return an.Scope(frm=start, to=end, member_id=member_id, task_type_id=task_type_id)


Scope = Depends(scope)
DB = Depends(get_session)


@router.get("/summary")
async def summary(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.summary(db, s)


@router.get("/trend")
async def trend(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.trend(db, s)


@router.get("/by-member")
async def by_member(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.by_member(db, s)


@router.get("/by-task-type")
async def by_task_type(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.by_task_type(db, s)


@router.get("/by-question-type")
async def by_question_type(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.by_question_type(db, s)


@router.get("/by-customer")
async def by_customer(limit: int = Query(20, ge=1, le=100), s: an.Scope = Scope,
                      db: AsyncSession = DB):
    return await an.by_customer(db, s, limit)



@router.get("/status-flow")
async def status_flow(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.status_flow(db, s)


@router.get("/cycle-time")
async def cycle_time(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.cycle_time(db, s)


@router.get("/plan-adherence")
async def plan_adherence(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.plan_adherence(db, s)


@router.get("/aging")
async def aging(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.aging(db, s, today())


@router.get("/due-risk")
async def due_risk(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.due_risk(db, s, today())


@router.get("/throughput")
async def throughput(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.throughput(db, s)


@router.get("/workload")
async def workload(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.workload(db, s)


@router.get("/open-items")
async def open_items(limit: int = Query(200, ge=1, le=1000), s: an.Scope = Scope,
                     db: AsyncSession = DB):
    return await an.open_items(db, s, today(), limit)


@router.get("/data-quality")
async def data_quality(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.data_quality(db, s)


@router.get("/ae-metrics")
async def ae_metrics(s: an.Scope = Scope, db: AsyncSession = DB):
    return await an.ae_metrics(db, s)
