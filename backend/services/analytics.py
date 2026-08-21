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
from datetime import UTC, date, timedelta

from sqlalchemy import Select, and_, case, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dates import TZ, day_bounds_utc
from core.orm import (
    AREA_LABELS,
    ASSESSMENT_REQUEST_TYPES,
    STATUSES,
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
    pipeline: str | None = None
    area: str | None = None


# Below this, a ticket was filed after the work finished rather than tracked
# through it — see cycle_time().
RETROACTIVE_MINUTES = 2


def _entry_where(s: Scope) -> list:
    where = [DailyEntry.entry_date.between(s.frm, s.to)]
    if s.member_id:
        where.append(DailyEntry.member_id == s.member_id)
    return where


def _item_where(s: Scope) -> list:
    """Every filter that narrows the task set. One list, used by both query
    builders — they drifted apart once already and an `area` filter silently
    applied to only one of them."""
    where = [
        *_entry_where(s),
        or_(DailyEntry.kind == "plan", EntryItem.plan_item_id.is_(None)),
    ]
    if s.task_type_id:
        where.append(EntryItem.task_type_id == s.task_type_id)
    if s.pipeline:
        where.append(EntryItem.pipeline == s.pipeline)

    assessments = sorted(ASSESSMENT_REQUEST_TYPES)
    if s.area == "content_assessment":
        where += [EntryItem.pipeline == "content_request",
                  EntryItem.request_type.in_(assessments)]
    elif s.area == "content_request":
        where += [EntryItem.pipeline == "content_request",
                  or_(EntryItem.request_type.is_(None),
                      EntryItem.request_type.notin_(assessments))]
    elif s.area:
        where.append(EntryItem.pipeline == s.area)
    return where


def tasks(s: Scope) -> Select:
    """Items joined to their entry, mirrors excluded. Base of most queries."""
    return (
        select(EntryItem, DailyEntry)
        .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
        .where(*_item_where(s))
    )


def _from_tasks(s: Scope, *cols) -> Select:
    """Same join and filters as tasks(), but selecting arbitrary columns."""
    return (
        select(*cols)
        .select_from(EntryItem)
        .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
        .where(*_item_where(s))
    )


def _effort():
    """Total minutes logged. SUM skips NULLs, so unlogged work contributes
    nothing rather than counting as zero-effort."""
    return func.coalesce(func.sum(EntryItem.effort_minutes), 0).label("effort_minutes")


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
        _effort(),
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
        "effort_minutes": int(row.effort_minutes),
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
            _effort(),
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
            "effort_minutes": int(getattr(task_rows.get(d), "effort_minutes", 0)),
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
            _effort(),
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
            "effort_minutes": int(r.effort_minutes),
            **{st: getattr(r, st) for st in STATUSES},
            "completion_rate": round(r.closed / r.tasks, 4) if r.tasks else None,
        }
        for r in rows
    ]


def _area_col():
    """Assessment work is a Request *type* inside Content Requests, not its own
    issue type, so the reporting areas don't line up 1:1 with pipelines."""
    assessments = ", ".join(f"'{v}'" for v in sorted(ASSESSMENT_REQUEST_TYPES))
    return case(
        (
            and_(EntryItem.pipeline == "content_request",
                 EntryItem.request_type.in_(sorted(ASSESSMENT_REQUEST_TYPES))),
            "content_assessment",
        ),
        else_=EntryItem.pipeline,
    ).label("area")


async def by_area(db: AsyncSession, s: Scope) -> list[dict]:
    """The Requests screen's split: Content Requests, Content Assessments,
    HC/HT and Technical Writing, each with its own effort."""
    area = _area_col()
    rows = await db.execute(
        _from_tasks(
            s, area,
            func.count().label("tasks"),
            func.coalesce(func.sum(EntryItem.count), 0).label("volume"),
            _effort(),
            func.count(distinct(DailyEntry.member_id)).label("members"),
            func.count(distinct(EntryItem.customer)).label("customers"),
            *_status_cols(),
        ).group_by(area).order_by(func.count().desc())
    )
    return [
        {
            "area": r.area,
            "label": AREA_LABELS.get(r.area, r.area.replace("_", " ").title()),
            "tasks": r.tasks, "volume": int(r.volume),
            "effort_minutes": int(r.effort_minutes),
            "members": r.members, "customers": r.customers,
            **{st: getattr(r, st) for st in STATUSES},
        }
        for r in rows
    ]


def _label(area: str) -> str:
    return AREA_LABELS.get(area, area.replace("_", " ").title())


async def area_by_member(db: AsyncSession, s: Scope) -> list[dict]:
    """Who spent their time in which stream.

    `by_area` answers how much went into Content Requests; this answers who put
    it there. The Requests screen showed a stream's total with no way to see
    that one person carried it — which is the question actually being asked when
    a stream looks busy.
    """
    area = _area_col()
    rows = await db.execute(
        _from_tasks(
            s, area,
            Member.display_name.label("member"),
            DailyEntry.member_id.label("member_id"),
            func.count().label("tasks"),
            _effort(),
            func.count().filter(EntryItem.status == "closed").label("closed"),
        )
        .join(Member, Member.id == DailyEntry.member_id)
        .group_by(area, Member.display_name, DailyEntry.member_id)
        .order_by(area, func.coalesce(func.sum(EntryItem.effort_minutes), 0).desc())
    )
    grouped: dict[str, dict] = {}
    for r in rows:
        bucket = grouped.setdefault(
            r.area, {"area": r.area, "label": _label(r.area),
                     "tasks": 0, "effort_minutes": 0, "members": []}
        )
        bucket["tasks"] += r.tasks
        bucket["effort_minutes"] += int(r.effort_minutes)
        bucket["members"].append({
            "member_id": r.member_id, "member": r.member, "tasks": r.tasks,
            "effort_minutes": int(r.effort_minutes), "closed": r.closed,
        })
    # Share is computed after the totals are known, so it always sums to 1.
    for bucket in grouped.values():
        total = bucket["effort_minutes"]
        for m in bucket["members"]:
            m["share_of_area"] = round(m["effort_minutes"] / total, 4) if total else None
    return sorted(grouped.values(), key=lambda b: -b["effort_minutes"])


async def effort_breakdown(db: AsyncSession, s: Scope) -> dict:
    """Where a total of logged minutes actually went.

    This is what a headline "40h" needs behind it. Every dimension is summed
    from the same `effort_minutes` the headline uses, so the parts reconcile
    with the whole rather than approximating it — and the individual tickets are
    listed, because a breakdown you can't trace to a ticket is just a smaller
    number to disbelieve.
    """
    area = _area_col()

    async def split(col, extra=None):
        rows = await db.execute(
            _from_tasks(s, col.label("key"), func.count().label("tasks"), _effort())
            .where(EntryItem.effort_minutes.isnot(None))
            .group_by(col)
            .order_by(func.coalesce(func.sum(EntryItem.effort_minutes), 0).desc())
            .limit(25)
            if extra is None else extra
        )
        return [{"key": r.key, "label": r.key, "tasks": r.tasks,
                 "effort_minutes": int(r.effort_minutes)} for r in rows]

    total = (await db.execute(
        _from_tasks(s, _effort(), func.count().label("tasks"),
                    func.count().filter(EntryItem.effort_minutes.is_(None)).label("unlogged"),
                    func.count().filter(EntryItem.effort_suspect).label("suspect"))
    )).one()

    by_area_rows = await split(area)
    for row in by_area_rows:
        row["label"] = _label(row["key"])

    tickets = await db.execute(
        _from_tasks(
            s,
            EntryItem.id.label("id"),
            EntryItem.notes.label("notes"),
            EntryItem.effort_minutes.label("effort_minutes"),
            EntryItem.effort_suspect.label("suspect"),
            EntryItem.jira_issue_key.label("jira_issue_key"),
            EntryItem.jira_issue_url.label("jira_issue_url"),
            EntryItem.customer.label("customer"),
            EntryItem.status.label("status"),
            DailyEntry.entry_date.label("entry_date"),
            Member.display_name.label("member"),
            area,
        )
        .join(Member, Member.id == DailyEntry.member_id)
        .where(EntryItem.effort_minutes.isnot(None), EntryItem.effort_minutes > 0)
        .order_by(EntryItem.effort_minutes.desc())
        .limit(50)
    )
    return {
        "effort_minutes": int(total.effort_minutes),
        "tasks": total.tasks,
        # Both caveats travel with the number rather than sitting on another
        # screen: 12% of tickets carry no effort at all.
        "tasks_without_effort": total.unlogged,
        "tasks_with_suspect_effort": total.suspect,
        "by_area": by_area_rows,
        "by_task_type": await split(TaskType.name, extra=(
            _from_tasks(s, TaskType.name.label("key"), func.count().label("tasks"), _effort())
            .join(TaskType, TaskType.id == EntryItem.task_type_id)
            .where(EntryItem.effort_minutes.isnot(None))
            .group_by(TaskType.name)
            .order_by(func.coalesce(func.sum(EntryItem.effort_minutes), 0).desc())
            .limit(25)
        )),
        "by_customer": await split(
            func.coalesce(EntryItem.customer, "(no customer)")),
        "by_member": await split(Member.display_name, extra=(
            _from_tasks(s, Member.display_name.label("key"), func.count().label("tasks"), _effort())
            .join(Member, Member.id == DailyEntry.member_id)
            .where(EntryItem.effort_minutes.isnot(None))
            .group_by(Member.display_name)
            .order_by(func.coalesce(func.sum(EntryItem.effort_minutes), 0).desc())
            .limit(25)
        )),
        "top_tickets": [
            {"id": r.id, "notes": r.notes, "effort_minutes": r.effort_minutes,
             "suspect": r.suspect, "jira_issue_key": r.jira_issue_key,
             "jira_issue_url": r.jira_issue_url, "customer": r.customer,
             "status": r.status, "entry_date": r.entry_date.isoformat(),
             "member": r.member, "area": r.area, "area_label": _label(r.area)}
            for r in tickets
        ],
    }


async def quality_mix(db: AsyncSession, s: Scope) -> dict:
    """Priority and SLA, straight from Jira. Both were being fetched and thrown
    away until the fields were captured."""
    async def group(col):
        rows = await db.execute(
            _from_tasks(s, col.label("key"), func.count().label("tasks"), _effort())
            .group_by(col).order_by(func.count().desc())
        )
        return [{"key": r.key or "(none)", "tasks": r.tasks,
                 "effort_minutes": int(r.effort_minutes)} for r in rows]

    sla = (await db.execute(
        _from_tasks(
            s,
            func.count().filter(EntryItem.sla_met.is_(True)).label("met"),
            func.count().filter(EntryItem.sla_met.is_(False)).label("missed"),
        )
    )).one()
    return {
        "by_priority": await group(EntryItem.priority),
        "sla_met": sla.met,
        "sla_missed": sla.missed,
        # Jira only evaluates an SLA on about half the issues, so a bare
        # "met" count would read as a pass rate over everything.
        "sla_rate": round(sla.met / (sla.met + sla.missed), 4)
        if (sla.met + sla.missed) else None,
    }


async def by_request_type(db: AsyncSession, s: Scope) -> list[dict]:
    """Inside Content Requests: what kind of request was it?"""
    rows = await db.execute(
        _from_tasks(
            s, EntryItem.request_type,
            func.count().label("tasks"), _effort(),
        )
        .where(EntryItem.request_type.isnot(None))
        .group_by(EntryItem.request_type)
        .order_by(func.count().desc())
    )
    return [{"request_type": r.request_type, "tasks": r.tasks,
             "effort_minutes": int(r.effort_minutes)} for r in rows]


async def by_pipeline(db: AsyncSession, s: Scope) -> list[dict]:
    """The streams of work: Content Tasks, Content Requests, HC/HT, Technical
    writing. `external_issue_type` is carried through so the UI can label each
    with Jira's own words rather than our slug."""
    rows = await db.execute(
        _from_tasks(
            s,
            EntryItem.pipeline,
            func.max(EntryItem.external_issue_type).label("label"),
            func.count().label("tasks"),
            func.coalesce(func.sum(EntryItem.count), 0).label("volume"),
            _effort(),
            func.count(distinct(DailyEntry.member_id)).label("members"),
            func.count(distinct(EntryItem.customer)).label("customers"),
            *_status_cols(),
        )
        .group_by(EntryItem.pipeline)
        .order_by(func.count().desc())
    )
    return [
        {
            "pipeline": r.pipeline,
            "label": r.label or r.pipeline.replace("_", " ").title(),
            "tasks": r.tasks, "volume": int(r.volume),
            "effort_minutes": int(r.effort_minutes),
            "members": r.members, "customers": r.customers,
            **{st: getattr(r, st) for st in STATUSES},
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
            _effort(),
            *_status_cols(),
        )
        .join(TaskType, TaskType.id == EntryItem.task_type_id)
        .group_by(TaskType.name)
        .order_by(func.count().desc())
    )
    return [
        {"task_type": r.task_type, "tasks": r.tasks, "volume": int(r.volume),
         "effort_minutes": int(r.effort_minutes),
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
            _effort(),
            func.count().filter(EntryItem.status != "closed").label("outstanding"),
        )
        .where(func.trim(func.coalesce(EntryItem.customer, "")) != "")
        .group_by(func.trim(EntryItem.customer))
        .order_by(func.count().desc())
        .limit(limit)
    )
    return [{"customer": r.customer, "tasks": r.tasks, "volume": int(r.volume),
             "effort_minutes": int(r.effort_minutes),
             "outstanding": r.outstanding} for r in rows]



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
    """Elapsed time from raised to resolved.

    Jira's own `created`/`resolutiondate` first, our status events only as a
    fallback for work that never went to Jira. Deriving this from status events
    alone produced a median of 0.0h across 995 closed tasks: an imported row
    gets exactly one event, so `closed_at - opened_at` was always zero. The
    events are still the only source for web-entered work, hence the coalesce
    rather than a straight swap.
    """
    ev = _closed_at()
    opened = func.coalesce(EntryItem.external_created_at, ev.c.opened_at)
    closed = func.coalesce(EntryItem.resolved_at, ev.c.closed_at)
    hours = func.extract("epoch", closed - opened) / 3600.0
    median = func.percentile_cont(0.5).within_group(hours.asc())
    p90 = func.percentile_cont(0.9).within_group(hours.asc())
    # Jira resolves 78% of issues; the rest are still open or were closed
    # without a resolution. Reporting a median without saying what it covers is
    # how the 0.0h figure went unquestioned for as long as it did.
    resolved = and_(closed.isnot(None), closed >= opened)
    # Much of this team files the ticket once the work is already done: 72% of
    # tickets since 3 Aug were created and resolved inside 15 minutes, carrying
    # 121 hours of logged effort between them. For those, created -> resolved
    # measures how long the paperwork took, not the work, and including them
    # pulled the recent median down to 0.04h. Two minutes is the cut — nobody
    # raises a ticket and genuinely finishes it inside that.
    retroactive = hours < (RETROACTIVE_MINUTES / 60.0)
    measurable = and_(resolved, ~retroactive)

    def q(*cols):
        return (
            _from_tasks(s, *cols)
            .outerjoin(ev, ev.c.item_id == EntryItem.id)
            .where(measurable)
        )

    overall = (await db.execute(
        q(func.count().label("n"), median.label("median"), p90.label("p90"))
    )).one()
    # Denominator is finished work, not `status = 'closed'`: an issue can carry
    # a resolution while our status map still reads it as open, which made
    # coverage come out at 1.001 — more measured than eligible.
    counts = (await db.execute(
        _from_tasks(
            s,
            func.count().filter(or_(EntryItem.status == "closed", closed.isnot(None)))
            .label("eligible"),
            func.count().filter(and_(resolved, retroactive)).label("retro"),
        ).outerjoin(ev, ev.c.item_id == EntryItem.id)
    )).one()
    eligible = counts.eligible

    per_member = await db.execute(
        q(Member.display_name.label("member"), func.count().label("n"), median.label("median"))
        .join(Member, Member.id == DailyEntry.member_id)
        .group_by(Member.display_name)
        .order_by(median.desc())
    )
    per_type = await db.execute(
        q(TaskType.name.label("task_type"), func.count().label("n"), median.label("median"))
        .join(TaskType, TaskType.id == EntryItem.task_type_id)
        .group_by(TaskType.name)
        .order_by(median.desc())
    )
    r2 = lambda v: round(float(v), 2) if v is not None else None
    return {
        "closed_tasks": overall.n,
        "measured_of_closed": eligible,
        "filed_retroactively": counts.retro,
        "coverage": round(overall.n / eligible, 4) if eligible else None,
        "median_hours": r2(overall.median),
        "p90_hours": r2(overall.p90),
        "by_member": [{"member": r.member, "closed_tasks": r.n, "median_hours": r2(r.median)}
                      for r in per_member],
        "by_task_type": [{"task_type": r.task_type, "closed_tasks": r.n,
                          "median_hours": r2(r.median)} for r in per_type],
    }


async def plan_adherence(db: AsyncSession, s: Scope) -> list[dict]:
    """Of what was planned, how much got reported on and how much closed. This
    is the point of a plan/update tracker and it was never measurable before.

    Only plans a person actually filed count. The Jira backfill files its issues
    under synthetic `source='jira'` plan entries, and counting those made
    adherence meaningless — Archita read `planned 229, reported 0, 0%` purely
    because 229 backfilled tickets were being scored as unreported plans.
    """
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
        .where(*_entry_where(s), DailyEntry.kind == "plan", DailyEntry.source != "jira")
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


async def plan_daily_status(db: AsyncSession, s: Scope) -> list[dict]:
    """Per member, per day: did they file a plan, did they log an update.

    `plan_adherence` collapses the whole range into one row per member; this
    keeps the day so a board can show the pattern over time. Same Jira-sync
    exclusion on the plan side as `plan_adherence` — a backfilled ticket isn't
    someone filing a plan. The Jira sync never creates `update` rows, so that
    side needs no such filter (matches `today_status` in services/entries.py).

    "Updated" also counts a status-only change made straight from My Day
    (`patch_item`, no separate `update` entry filed) — otherwise a member who
    only ever closes tickets that way never shows as having reported.
    """
    planned = {
        (r.member_id, r.entry_date) for r in await db.execute(
            select(DailyEntry.member_id, DailyEntry.entry_date)
            .where(*_entry_where(s), DailyEntry.kind == "plan", DailyEntry.source != "jira")
            .distinct()
        )
    }
    range_start, _ = day_bounds_utc(s.frm)
    _, range_end = day_bounds_utc(s.to)
    updated = {
        (r.member_id, r.entry_date) for r in await db.execute(
            select(DailyEntry.member_id, DailyEntry.entry_date)
            .where(*_entry_where(s), DailyEntry.kind == "update")
            .distinct()
        )
    }
    status_change_where = [
        EntryItemStatusEvent.source == "web",
        # Excludes an item's creation event (from_status IS NULL) — filing a
        # plan shouldn't itself count as an update.
        EntryItemStatusEvent.from_status.is_not(None),
        EntryItemStatusEvent.changed_at >= range_start,
        EntryItemStatusEvent.changed_at < range_end,
    ]
    if s.member_id:
        status_change_where.append(DailyEntry.member_id == s.member_id)
    for r in await db.execute(
        select(DailyEntry.member_id, EntryItemStatusEvent.changed_at)
        .select_from(EntryItemStatusEvent)
        .join(EntryItem, EntryItem.id == EntryItemStatusEvent.entry_item_id)
        .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
        .where(*status_change_where)
    ):
        updated.add((r.member_id, r.changed_at.replace(tzinfo=UTC).astimezone(TZ).date()))
    # Tickets logged for that day — same de-dup as `tasks()`, so an update row
    # that's just progress on an existing plan item isn't counted twice.
    created: dict[tuple[int, date], int] = {}
    for r in await db.execute(
        select(DailyEntry.member_id, DailyEntry.entry_date)
        .select_from(EntryItem).join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
        .where(*_item_where(s))
    ):
        created[r.member_id, r.entry_date] = created.get((r.member_id, r.entry_date), 0) + 1
    # Closed *on* that day, not planned that day — a ticket planned Monday and
    # closed Wednesday belongs to Wednesday's count, not Monday's. `changed_at`
    # is a naive-UTC instant, so the range and the day it's bucketed into both
    # have to go through day_bounds_utc — comparing it to a bare date silently
    # treats the boundary as UTC midnight, 5:30 off from midnight IST.
    closed: dict[tuple[int, date], int] = {}
    closed_where = [
        EntryItemStatusEvent.to_status == "closed",
        EntryItemStatusEvent.changed_at >= range_start,
        EntryItemStatusEvent.changed_at < range_end,
    ]
    if s.member_id:
        closed_where.append(DailyEntry.member_id == s.member_id)
    for r in await db.execute(
        select(DailyEntry.member_id, EntryItemStatusEvent.changed_at)
        .select_from(EntryItemStatusEvent)
        .join(EntryItem, EntryItem.id == EntryItemStatusEvent.entry_item_id)
        .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
        .where(*closed_where)
    ):
        d = r.changed_at.replace(tzinfo=UTC).astimezone(TZ).date()
        closed[r.member_id, d] = closed.get((r.member_id, d), 0) + 1

    member_where = [Member.is_active.is_(True)]
    if s.member_id:
        member_where.append(Member.id == s.member_id)
    members = await db.execute(
        select(Member.id, Member.display_name)
        .where(*member_where)
        .order_by(Member.display_name)
    )
    days = _days(s.frm, s.to)
    return [
        {
            "member_id": member_id, "member": member, "entry_date": d.isoformat(),
            "planned": (member_id, d) in planned, "updated": (member_id, d) in updated,
            "created": created.get((member_id, d), 0), "closed": closed.get((member_id, d), 0),
        }
        for member_id, member in members
        for d in days
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
            _effort(),
        )
        .join(Member, Member.id == DailyEntry.member_id)
        .group_by(Member.display_name, DailyEntry.entry_date)
    )
    return [{"member": r.member, "date": r.d.isoformat(), "tasks": r.tasks,
             "volume": int(r.volume), "effort_minutes": int(r.effort_minutes)}
            for r in rows]


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
        func.count().filter(EntryItem.effort_minutes.is_(None)).label("no_effort"),
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
            "effort": row.no_effort,
        },
        "plans_with_unreported_tasks": silent or 0,
        "tasks_on_retired_task_types": inactive_types or 0,
    }
