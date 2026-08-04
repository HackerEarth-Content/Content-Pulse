"""AE daily updates. Metrics are rows, not columns — adding one is an insert."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.orm import AEDailyMetric, AEDailyUpdate, AEMetricDefinition, Member
from services.entries import err

AE_ROLES = ("ae", "manager", "admin")


async def metric_defs(db: AsyncSession) -> list[AEMetricDefinition]:
    return list(await db.scalars(
        select(AEMetricDefinition)
        .where(AEMetricDefinition.is_active.is_(True))
        .order_by(AEMetricDefinition.sort_order)
    ))


def serialise(u: AEDailyUpdate) -> dict:
    return {
        "id": u.id,
        "member_id": u.member_id,
        "member": u.member.display_name,
        "entry_date": u.entry_date.isoformat(),
        "notes": u.notes,
        "updated_at": u.updated_at,
        "metrics": {m.metric.key: m.value for m in u.metrics},
    }


def _loaded(stmt):
    return stmt.options(selectinload(AEDailyUpdate.metrics).selectinload(AEDailyMetric.metric))


async def get_one(db: AsyncSession, member_id: int, on: date) -> AEDailyUpdate | None:
    return await db.scalar(_loaded(select(AEDailyUpdate).where(
        AEDailyUpdate.member_id == member_id, AEDailyUpdate.entry_date == on
    )))


async def list_range(
    db: AsyncSession, frm: date, to: date, member_id: int | None = None
) -> list[AEDailyUpdate]:
    where = [AEDailyUpdate.entry_date.between(frm, to)]
    if member_id:
        where.append(AEDailyUpdate.member_id == member_id)
    return list(await db.scalars(
        _loaded(select(AEDailyUpdate).where(*where))
        .order_by(AEDailyUpdate.entry_date.desc())
    ))


async def upsert(
    db: AsyncSession, *, member_id: int, entry_date: date, notes: str,
    metrics: dict[str, int], version: datetime | None, user_id: str | None,
) -> AEDailyUpdate:
    member = await db.get(Member, member_id)
    if member is None:
        raise err(422, "unknown_member", f"No member with id {member_id}.")
    if member.role not in AE_ROLES:
        raise err(403, "not_an_ae", f"{member.display_name} isn't an Application Engineer.")

    defs = {d.key: d for d in await metric_defs(db)}
    if unknown := sorted(set(metrics) - set(defs)):
        raise err(422, "unknown_metric", f"No such metric(s): {', '.join(unknown)}.")
    if bad := sorted(k for k, v in metrics.items() if v < 0):
        raise err(422, "negative_metric", f"Values must be >= 0: {', '.join(bad)}.")

    existing = await get_one(db, member_id, entry_date)
    if existing:
        # Two people editing the same member/day silently clobbered each other
        # in the Django app — get_or_create then overwrite. Make it a conflict.
        if version is None or version != existing.updated_at:
            raise err(409, "stale_update",
                      "This day was saved by someone else. Reload before saving.",
                      updated_at=existing.updated_at.isoformat())
        existing.notes = notes
        by_metric = {m.metric_id: m for m in existing.metrics}
        for key, value in metrics.items():
            metric_id = defs[key].id
            if metric_id in by_metric:
                by_metric[metric_id].value = value
            else:
                existing.metrics.append(AEDailyMetric(metric_id=metric_id, value=value))
        await db.commit()
        return await get_one(db, member_id, entry_date)

    row = AEDailyUpdate(
        member_id=member_id, entry_date=entry_date, notes=notes,
        created_by_user_id=user_id,
        metrics=[AEDailyMetric(metric_id=defs[k].id, value=v) for k, v in metrics.items()],
    )
    db.add(row)
    await db.commit()
    return await get_one(db, member_id, entry_date)
