"""Every aggregate the dashboard shows, as SQL.

The Django app pulled 500 rows into Python and counted them in loops, which
silently truncated any range wider than a couple of weeks. Nothing here loads
rows to count them.

One definition matters everywhere below: a **task** is a plan row, or a piece of
extra work. The update rows that mirror a plan row are excluded — they're the
same task reported a second time, and counting both is what made the old
dashboard's totals drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Select, and_, case, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.orm import (
    STATUSES,
    AEDailyMetric,
    AEDailyUpdate,
    AEMetricDefinition,
    DailyEntry,
    EntryItem,
    EntryItemStatusEvent,
    Member,
    QuestionType,
    TaskType,
)


@dataclass(frozen=True)
class Scope:
    frm: date
    to: date
    member_id: int | None = None
    task_type_id: int | None = None


def _entry_where(s: Scope) -> list:
    where = [DailyEntry.entry_date.between(s.frm, s.to)]
    if s.member_id:
        where.append(DailyEntry.member_id == s.member_id)
    return where


def tasks(s: Scope) -> Select:
    """Items joined to their entry, mirrors excluded. Base of most queries."""
    stmt = (
        select(EntryItem, DailyEntry)
        .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
        .where(
            *_entry_where(s),
            or_(DailyEntry.kind == "plan", EntryItem.plan_item_id.is_(None)),
        )
    )
    if s.task_type_id:
        stmt = stmt.where(EntryItem.task_type_id == s.task_type_id)
    return stmt


def _from_tasks(s: Scope, *cols) -> Select:
    """Same join and filters as tasks(), but selecting arbitrary columns."""
    stmt = (
        select(*cols)
        .select_from(EntryItem)
        .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
        .where(
            *_entry_where(s),
            or_(DailyEntry.kind == "plan", EntryItem.plan_item_id.is_(None)),
        )
    )
    if s.task_type_id:
        stmt = stmt.where(EntryItem.task_type_id == s.task_type_id)
    return stmt


def _status_cols() -> list:
    return [
        func.count().filter(EntryItem.status == st).label(st) for st in STATUSES
    ]


def _days(frm: date, to: date) -> list[date]:
    return [frm + timedelta(days=i) for i in range((to - frm).days + 1)]


# ── headline ──────────────────────────────────────────────────────────────────


async def summary(db: AsyncSession, s: Scope) -> dict:
    row = (await db.execute(_from_tasks(
        s,
        func.count().label("tasks"),
        func.coalesce(func.sum(EntryItem.count), 0).label("volume"),
        func.count(distinct(DailyEntry.member_id)).label("members"),
        *_status_cols(),
    ))).one()

    entries = (await db.execute(
        select(
            func.count().filter(DailyEntry.kind == "plan").label("plans"),
            func.count().filter(DailyEntry.kind == "update").label("updates"),
        ).where(*_entry_where(s))
    )).one()

    done = row.closed
    return {
        "range": {"from": s.frm.isoformat(), "to": s.to.isoformat()},
        "members": row.members,
        "tasks": row.tasks,
        "volume": int(row.volume),
        "plans": entries.plans,
        "updates": entries.updates,
        **{st: getattr(row, st) for st in STATUSES},
        "completion_rate": round(done / row.tasks, 4) if row.tasks else None,
    }


async def trend(db: AsyncSession, s: Scope) -> list[dict]:
    """Zero-filled — a chart that skips weekends lies about the gap."""
    task_rows = {
        r.d: r for r in await db.execute(_from_tasks(
            s,
            DailyEntry.entry_date.label("d"),
            func.count().label("tasks"),
            func.coalesce(func.sum(EntryItem.count), 0).label("volume"),
            func.count().filter(EntryItem.status == "closed").label("closed"),
        ).group_by(DailyEntry.entry_date))
    }
    entry_rows = {
        r.d: r for r in await db.execute(
            select(
                DailyEntry.entry_date.label("d"),
                func.count().filter(DailyEntry.kind == "plan").label("plans"),
                func.count().filter(DailyEntry.kind == "update").label("updates"),
            ).where(*_entry_where(s)).group_by(DailyEntry.entry_date)
        )
    }
    return [
        {
            "date": d.isoformat(),
            "tasks": getattr(task_rows.get(d), "tasks", 0),
            "volume": int(getattr(task_rows.get(d), "volume", 0)),
            "closed": getattr(task_rows.get(d), "closed", 0),
            "plans": getattr(entry_rows.get(d), "plans", 0),
            "updates": getattr(entry_rows.get(d), "updates", 0),
        }
        for d in _days(s.frm, s.to)
    ]


# ── breakdowns ────────────────────────────────────────────────────────────────


async def by_member(db: AsyncSession, s: Scope) -> list[dict]:
    rows = await db.execute(
        _from_tasks(
            s,
            Member.id.label("member_id"),
            Member.display_name.label("member"),
            func.count().label("tasks"),
            func.coalesce(func.sum(EntryItem.count), 0).label("volume"),
            *_status_cols(),
        )
        .join(Member, Member.id == DailyEntry.member_id)
        .group_by(Member.id, Member.display_name)
        .order_by(func.count().desc())
    )
    return [
        {
            "member_id": r.member_id, "member": r.member,
            "tasks": r.tasks, "volume": int(r.volume),
            **{st: getattr(r, st) for st in STATUSES},
            "completion_rate": round(r.closed / r.tasks, 4) if r.tasks else None,
        }
        for r in rows
    ]


async def by_task_type(db: AsyncSession, s: Scope) -> list[dict]:
    rows = await db.execute(
        _from_tasks(
            s,
            TaskType.name.label("task_type"),
            func.count().label("tasks"),
            func.coalesce(func.sum(EntryItem.count), 0).label("volume"),
            *_status_cols(),
        )
        .join(TaskType, TaskType.id == EntryItem.task_type_id)
        .group_by(TaskType.name)
        .order_by(func.count().desc())
    )
    return [
        {"task_type": r.task_type, "tasks": r.tasks, "volume": int(r.volume),
         **{st: getattr(r, st) for st in STATUSES}}
        for r in rows
    ]


async def by_question_type(db: AsyncSession, s: Scope) -> list[dict]:
    rows = await db.execute(
        _from_tasks(
            s,
            QuestionType.name.label("question_type"),
            func.count().label("tasks"),
            func.coalesce(func.sum(EntryItem.count), 0).label("volume"),
        )
        .join(QuestionType, QuestionType.id == EntryItem.question_type_id)
        .group_by(QuestionType.name)
        .order_by(func.count().desc())
    )
    return [{"question_type": r.question_type, "tasks": r.tasks, "volume": int(r.volume)}
            for r in rows]


async def by_customer(db: AsyncSession, s: Scope, limit: int = 20) -> list[dict]:
    """`customer` is free text on every item and the old app never aggregated it."""
    rows = await db.execute(
        _from_tasks(
            s,
            func.trim(EntryItem.customer).label("customer"),
            func.count().label("tasks"),
            func.coalesce(func.sum(EntryItem.count), 0).label("volume"),
            func.count().filter(EntryItem.status != "closed").label("outstanding"),
        )
        .where(func.trim(func.coalesce(EntryItem.customer, "")) != "")
        .group_by(func.trim(EntryItem.customer))
        .order_by(func.count().desc())
        .limit(limit)
    )
    return [{"customer": r.customer, "tasks": r.tasks, "volume": int(r.volume),
             "outstanding": r.outstanding} for r in rows]


async def status_distribution(db: AsyncSession, s: Scope) -> list[dict]:
    rows = await db.execute(
        _from_tasks(s, EntryItem.status, func.count().label("tasks"))
        .group_by(EntryItem.status)
    )
    counts = {r.status: r.tasks for r in rows}
    return [{"status": st, "tasks": counts.get(st, 0)} for st in STATUSES]


# ── flow, timing, adherence ───────────────────────────────────────────────────


async def status_flow(db: AsyncSession, s: Scope) -> list[dict]:
    """Transition matrix. blocked -> closed vs blocked -> open is the rework
    signal; the old app kept no history, so this was unanswerable."""
    rows = await db.execute(
        select(
            EntryItemStatusEvent.from_status,
            EntryItemStatusEvent.to_status,
            func.count().label("n"),
        )
        .join(EntryItem, EntryItem.id == EntryItemStatusEvent.entry_item_id)
        .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
        .where(*_entry_where(s), EntryItemStatusEvent.from_status.isnot(None))
        .group_by(EntryItemStatusEvent.from_status, EntryItemStatusEvent.to_status)
        .order_by(func.count().desc())
    )
    return [{"from": r.from_status, "to": r.to_status, "count": r.n} for r in rows]


def _closed_at():
    """First time each item reached closed, and when it first appeared."""
    return (
        select(
            EntryItemStatusEvent.entry_item_id.label("item_id"),
            func.min(EntryItemStatusEvent.changed_at).label("opened_at"),
            func.min(EntryItemStatusEvent.changed_at)
            .filter(EntryItemStatusEvent.to_status == "closed")
            .label("closed_at"),
        )
        .group_by(EntryItemStatusEvent.entry_item_id)
        .subquery()
    )


async def cycle_time(db: AsyncSession, s: Scope) -> dict:
    ev = _closed_at()
    hours = func.extract("epoch", ev.c.closed_at - ev.c.opened_at) / 3600.0
    median = func.percentile_cont(0.5).within_group(hours.asc())
    p90 = func.percentile_cont(0.9).within_group(hours.asc())

    base = (
        _from_tasks(s, func.count().label("n"), median.label("median"), p90.label("p90"))
        .join(ev, ev.c.item_id == EntryItem.id)
        .where(ev.c.closed_at.isnot(None))
    )
    overall = (await db.execute(base)).one()

    per_member = await db.execute(
        _from_tasks(s, Member.display_name.label("member"),
                    func.count().label("n"), median.label("median"))
        .join(ev, ev.c.item_id == EntryItem.id)
        .join(Member, Member.id == DailyEntry.member_id)
        .where(ev.c.closed_at.isnot(None))
        .group_by(Member.display_name)
        .order_by(median.desc())
    )
    per_type = await db.execute(
        _from_tasks(s, TaskType.name.label("task_type"),
                    func.count().label("n"), median.label("median"))
        .join(ev, ev.c.item_id == EntryItem.id)
        .join(TaskType, TaskType.id == EntryItem.task_type_id)
        .where(ev.c.closed_at.isnot(None))
        .group_by(TaskType.name)
        .order_by(median.desc())
    )
    r2 = lambda v: round(float(v), 2) if v is not None else None
    return {
        "closed_tasks": overall.n,
        "median_hours": r2(overall.median),
        "p90_hours": r2(overall.p90),
        "by_member": [{"member": r.member, "closed_tasks": r.n, "median_hours": r2(r.median)}
                      for r in per_member],
        "by_task_type": [{"task_type": r.task_type, "closed_tasks": r.n,
                          "median_hours": r2(r.median)} for r in per_type],
    }


async def plan_adherence(db: AsyncSession, s: Scope) -> list[dict]:
    """Of what was planned, how much got reported on and how much closed. This
    is the point of a plan/update tracker and it was never measurable before."""
    mirror = (
        select(EntryItem.plan_item_id)
        .where(EntryItem.plan_item_id.isnot(None))
        .distinct()
        .subquery()
    )
    reported = EntryItem.id.in_(select(mirror.c.plan_item_id))
    rows = await db.execute(
        select(
            Member.id.label("member_id"),
            Member.display_name.label("member"),
            func.count().label("planned"),
            func.count().filter(reported).label("reported"),
            func.count().filter(EntryItem.status == "closed").label("closed"),
            func.count().filter(and_(~reported, EntryItem.status != "closed"))
            .label("no_update"),
        )
        .select_from(EntryItem)
        .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
        .join(Member, Member.id == DailyEntry.member_id)
        .where(*_entry_where(s), DailyEntry.kind == "plan")
        .group_by(Member.id, Member.display_name)
        .order_by(func.count().desc())
    )
    return [
        {
            "member_id": r.member_id, "member": r.member, "planned": r.planned,
            "reported": r.reported, "closed": r.closed, "no_update": r.no_update,
            "report_rate": round(r.reported / r.planned, 4) if r.planned else None,
            "close_rate": round(r.closed / r.planned, 4) if r.planned else None,
        }
        for r in rows
    ]


async def aging(db: AsyncSession, s: Scope, today: date) -> dict:
    """Open work by age. Buckets match the plan: 0-2 / 3-7 / 8-14 / 15+."""
    age = today - DailyEntry.entry_date
    bucket = case(
        (age <= 2, "0-2"), (age <= 7, "3-7"), (age <= 14, "8-14"), else_="15+"
    ).label("bucket")
    rows = await db.execute(
        _from_tasks(s, bucket, func.count().label("tasks"))
        .where(EntryItem.status != "closed")
        .group_by(bucket)
    )
    counts = {r.bucket: r.tasks for r in rows}
    return {"buckets": [{"bucket": b, "tasks": counts.get(b, 0)}
                        for b in ("0-2", "3-7", "8-14", "15+")]}


async def due_risk(db: AsyncSession, s: Scope, today: date) -> dict:
    """`due_at` is captured on every task and then used for nothing."""
    week_end = today + timedelta(days=7)
    row = (await db.execute(
        _from_tasks(
            s,
            func.count().filter(EntryItem.due_at < today).label("overdue"),
            func.count().filter(EntryItem.due_at == today).label("due_today"),
            func.count().filter(EntryItem.due_at.between(today, week_end)).label("due_week"),
            func.count().filter(EntryItem.due_at.is_(None)).label("no_due_date"),
        ).where(EntryItem.status != "closed")
    )).one()
    return {"overdue": row.overdue, "due_today": row.due_today,
            "due_this_week": row.due_week, "no_due_date": row.no_due_date}


async def throughput(db: AsyncSession, s: Scope) -> list[dict]:
    """Tasks actually closed per day, from the event log — not 'currently
    closed', which can't tell you when the work happened."""
    rows = await db.execute(
        select(
            func.date(EntryItemStatusEvent.changed_at).label("d"),
            func.count(distinct(EntryItemStatusEvent.entry_item_id)).label("closed"),
        )
        .join(EntryItem, EntryItem.id == EntryItemStatusEvent.entry_item_id)
        .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
        .where(
            *_entry_where(s),
            EntryItemStatusEvent.to_status == "closed",
            or_(DailyEntry.kind == "plan", EntryItem.plan_item_id.is_(None)),
        )
        .group_by(func.date(EntryItemStatusEvent.changed_at))
    )
    counts = {r.d: r.closed for r in rows}
    return [{"date": d.isoformat(), "closed": counts.get(d, 0)} for d in _days(s.frm, s.to)]


async def workload(db: AsyncSession, s: Scope) -> list[dict]:
    rows = await db.execute(
        _from_tasks(
            s,
            Member.display_name.label("member"),
            DailyEntry.entry_date.label("d"),
            func.count().label("tasks"),
            func.coalesce(func.sum(EntryItem.count), 0).label("volume"),
        )
        .join(Member, Member.id == DailyEntry.member_id)
        .group_by(Member.display_name, DailyEntry.entry_date)
    )
    return [{"member": r.member, "date": r.d.isoformat(), "tasks": r.tasks,
             "volume": int(r.volume)} for r in rows]


async def open_items(db: AsyncSession, s: Scope, today: date, limit: int = 200) -> list[dict]:
    rows = await db.execute(
        _from_tasks(
            s,
            EntryItem.id, EntryItem.status, EntryItem.notes, EntryItem.customer,
            EntryItem.due_at, EntryItem.count,
            TaskType.name.label("task_type"),
            Member.display_name.label("member"),
            DailyEntry.entry_date,
        )
        .join(TaskType, TaskType.id == EntryItem.task_type_id)
        .join(Member, Member.id == DailyEntry.member_id)
        .where(EntryItem.status != "closed")
        .order_by(DailyEntry.entry_date, Member.display_name)
        .limit(limit)
    )
    return [
        {
            "id": r.id, "member": r.member, "task_type": r.task_type,
            "status": r.status, "customer": r.customer, "count": r.count,
            "notes": r.notes, "entry_date": r.entry_date.isoformat(),
            "due_at": r.due_at.isoformat() if r.due_at else None,
            "age_days": (today - r.entry_date).days,
            "overdue": bool(r.due_at and r.due_at < today and r.status != "closed"),
        }
        for r in rows
    ]


async def data_quality(db: AsyncSession, s: Scope) -> dict:
    row = (await db.execute(_from_tasks(
        s,
        func.count().label("tasks"),
        func.count().filter(func.trim(func.coalesce(EntryItem.notes, "")) == "").label("no_notes"),
        func.count().filter(EntryItem.count.is_(None)).label("no_count"),
        func.count().filter(func.trim(func.coalesce(EntryItem.customer, "")) == "")
        .label("no_customer"),
        func.count().filter(EntryItem.question_type_id.is_(None)).label("no_question_type"),
        func.count().filter(EntryItem.due_at.is_(None)).label("no_due_date"),
    ))).one()

    # Plans nobody ever reported against — the loudest quality signal here.
    mirror = select(EntryItem.plan_item_id).where(EntryItem.plan_item_id.isnot(None))
    silent = await db.scalar(
        select(func.count(distinct(DailyEntry.id)))
        .select_from(DailyEntry)
        .join(EntryItem, EntryItem.entry_id == DailyEntry.id)
        .where(*_entry_where(s), DailyEntry.kind == "plan", EntryItem.id.notin_(mirror))
    )
    inactive_types = await db.scalar(
        _from_tasks(s, func.count())
        .join(TaskType, TaskType.id == EntryItem.task_type_id)
        .where(TaskType.is_active.is_(False))
    )
    return {
        "tasks": row.tasks,
        "missing": {
            "notes": row.no_notes, "count": row.no_count, "customer": row.no_customer,
            "question_type": row.no_question_type, "due_date": row.no_due_date,
        },
        "plans_with_unreported_tasks": silent or 0,
        "tasks_on_retired_task_types": inactive_types or 0,
    }


# ── AE metrics ────────────────────────────────────────────────────────────────


async def ae_metrics(db: AsyncSession, s: Scope) -> dict:
    where = [AEDailyUpdate.entry_date.between(s.frm, s.to)]
    if s.member_id:
        where.append(AEDailyUpdate.member_id == s.member_id)

    # Aggregate in range first, then LEFT JOIN the definitions onto it — a
    # metric with no data this period must report 0, not drop off the chart.
    sums = (
        select(AEDailyMetric.metric_id, func.sum(AEDailyMetric.value).label("total"))
        .join(AEDailyUpdate, AEDailyUpdate.id == AEDailyMetric.ae_daily_update_id)
        .where(*where)
        .group_by(AEDailyMetric.metric_id)
        .subquery()
    )
    totals = await db.execute(
        select(
            AEMetricDefinition.key, AEMetricDefinition.name,
            func.coalesce(sums.c.total, 0).label("total"),
        )
        .select_from(AEMetricDefinition)
        .join(sums, sums.c.metric_id == AEMetricDefinition.id, isouter=True)
        .where(AEMetricDefinition.is_active.is_(True))
        .order_by(AEMetricDefinition.sort_order)
    )
    per_member = await db.execute(
        select(
            Member.display_name.label("member"), AEMetricDefinition.key,
            func.sum(AEDailyMetric.value).label("total"),
        )
        .select_from(AEDailyMetric)
        .join(AEDailyUpdate, AEDailyUpdate.id == AEDailyMetric.ae_daily_update_id)
        .join(AEMetricDefinition, AEMetricDefinition.id == AEDailyMetric.metric_id)
        .join(Member, Member.id == AEDailyUpdate.member_id)
        .where(*where)
        .group_by(Member.display_name, AEMetricDefinition.key)
    )
    daily = await db.execute(
        select(
            AEDailyUpdate.entry_date.label("d"),
            func.sum(AEDailyMetric.value).label("total"),
        )
        .select_from(AEDailyMetric)
        .join(AEDailyUpdate, AEDailyUpdate.id == AEDailyMetric.ae_daily_update_id)
        .where(*where)
        .group_by(AEDailyUpdate.entry_date)
    )
    by_day = {r.d: r.total for r in daily}
    return {
        "totals": [{"key": r.key, "label": r.name, "total": int(r.total)} for r in totals],
        "by_member": [{"member": r.member, "key": r.key, "total": int(r.total)}
                      for r in per_member],
        "trend": [{"date": d.isoformat(), "total": int(by_day.get(d, 0))}
                  for d in _days(s.frm, s.to)],
    }
