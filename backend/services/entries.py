"""Plan/update creation, status cascade, and the queries behind the work log.

Routes stay thin — everything that decides something lives here.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.config import settings
from core.orm import DailyEntry, EntryItem, EntryItemStatusEvent, Member, TaskType
from schemas.entries import ItemIn, PlanIn, UpdateIn


def err(code_status: int, code: str, detail: str, **extra) -> HTTPException:
    return HTTPException(code_status, {"code": code, "detail": detail, **extra})


def _loaded(stmt: Select) -> Select:
    return stmt.options(selectinload(DailyEntry.items))


# A ticket earns its way through the workflow rather than jumping straight to
# an end state — "open" work has to be picked up (in_progress) before it can
# resolve, and once "closed" it's done for good, not reopened from here.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_progress"},
    "in_progress": {"blocked", "closed"},
    "blocked": {"in_progress"},
    "closed": set(),
}


def check_transition(current: str, requested: str, *, effort_minutes: int | None) -> None:
    if requested == current:
        return
    if requested not in ALLOWED_TRANSITIONS.get(current, set()):
        raise err(422, "bad_transition",
                  f"Can't move a {current} ticket straight to {requested}.",
                  current=current, requested=requested)
    # Leaving in-progress is the point at which time was actually spent — this
    # is where effort has to be on the record, not some vaguer "on any save".
    if current == "in_progress" and effort_minutes is None:
        raise err(422, "effort_required",
                  "Log the effort spent before moving this off In progress.")



async def record_status(
    db: AsyncSession, item: EntryItem, to_status: str, *,
    source: str = "web", note: str | None = None, user_id: str | None = None,
) -> None:
    """Append a transition row and move the item. No-ops when nothing changed,
    so re-saving an update doesn't inflate the throughput numbers."""
    if item.status == to_status:
        return
    db.add(EntryItemStatusEvent(
        entry_item_id=item.id, from_status=item.status,
        to_status=to_status, source=source, note=note, changed_by_user_id=user_id,
    ))
    item.status = to_status


async def _new_item(
    db: AsyncSession, entry: DailyEntry, data: ItemIn, sort_order: int,
    *, status_: str, user_id: str | None, plan_item: EntryItem | None = None,
) -> EntryItem:
    if not await db.get(TaskType, data.task_type_id):
        raise err(422, "unknown_task_type",
                  f"No task type with id {data.task_type_id}.")

    parent_issue_url = None
    if data.parent_issue_key:
        from integrations import jira

        try:
            found = await jira.issue_exists(db, data.parent_issue_key)
        except jira.JiraDisabled as e:
            raise err(422, "jira_unavailable",
                      f"Can't verify the parent ticket right now: {e}")
        except Exception as e:
            raise err(422, "jira_unavailable", f"Couldn't reach Jira to verify the parent ticket: {e}")
        if not found:
            raise err(422, "unknown_parent_issue",
                      f"{data.parent_issue_key} doesn't exist in Jira.")
        parent_issue_url = f"{settings.JIRA_BASE_URL}/browse/{data.parent_issue_key}"

    item = EntryItem(
        entry_id=entry.id, sort_order=sort_order, status=status_,
        plan_item_id=plan_item.id if plan_item else None,
        parent_issue_url=parent_issue_url,
        # `create_jira` is the request's word for it; `jira_wanted` is the
        # column. Mapped rather than renamed so the API reads as an instruction.
        jira_wanted=getattr(data, "create_jira", False),
        **data.model_dump(exclude={"status", "create_jira"}),
    )
    db.add(item)
    await db.flush()
    db.add(EntryItemStatusEvent(
        entry_item_id=item.id, to_status=status_, source=entry.source,
        note=data.notes, changed_by_user_id=user_id,
    ))
    return item


async def get_plan(db: AsyncSession, member_id: int, on: date) -> DailyEntry | None:
    return await db.scalar(_loaded(
        select(DailyEntry).where(
            DailyEntry.member_id == member_id,
            DailyEntry.entry_date == on,
            DailyEntry.kind == "plan",
        )
    ))


async def create_plan(db: AsyncSession, data: PlanIn, user_id: str | None) -> DailyEntry:
    if not await db.get(Member, data.member_id):
        raise err(422, "unknown_member",
                  f"No member with id {data.member_id}.")
    if existing := await get_plan(db, data.member_id, data.entry_date):
        raise err(409, "plan_exists",
                  "This member already has a plan for that date.", entry_id=existing.id)

    entry = DailyEntry(
        member_id=data.member_id, entry_date=data.entry_date, kind="plan",
        raw_text=data.raw_text, source="web", created_by_user_id=user_id,
        post_at=data.post_at,
    )
    db.add(entry)
    await db.flush()
    for i, item in enumerate(data.items):
        await _new_item(db, entry, item, i, status_=item.status, user_id=user_id)
    await db.commit()
    return await db.scalar(_loaded(select(DailyEntry).where(DailyEntry.id == entry.id)))


async def create_update(db: AsyncSession, data: UpdateIn, user_id: str | None) -> DailyEntry:
    if not await db.get(Member, data.member_id):
        raise err(422, "unknown_member",
                  f"No member with id {data.member_id}.")

    plan = await get_plan(db, data.member_id, data.entry_date)
    if data.plan_lines and plan is None:
        raise err(404, "no_plan",
                  "No plan exists for this member and date — log it as extra work instead.")

    # Every referenced plan row must still belong to *this* plan. Catches a form
    # submitted after the plan was edited, and a client sending someone else's ids.
    by_id = {i.id: i for i in (plan.items if plan else [])}
    if unknown := [ln.plan_item_id for ln in data.plan_lines if ln.plan_item_id not in by_id]:
        raise err(422, "plan_item_mismatch",
                  "The plan changed since this form was opened. Reload it.",
                  unknown_plan_item_ids=unknown)

    entry = DailyEntry(
        member_id=data.member_id, entry_date=data.entry_date, kind="update",
        raw_text=data.raw_text, source="web", created_by_user_id=user_id,
        post_at=data.post_at,
    )
    db.add(entry)
    await db.flush()

    order = 0
    for line in data.plan_lines:
        plan_item = by_id[line.plan_item_id]
        if line.count is not None:
            plan_item.count = line.count
        plan_item.due_at = line.due_at
        # Effort accrues on the plan row, because analytics counts plan rows and
        # skips the mirrors. 2h Monday + 3h Tuesday on one task is 5h, not 3h.
        if line.effort_minutes is not None:
            plan_item.effort_minutes = (plan_item.effort_minutes or 0) + line.effort_minutes
        # Checked against the effort *after* accrual above, so effort reported
        # in this same line already counts toward the "leaving in-progress"
        # requirement rather than needing a separate prior save.
        check_transition(plan_item.status, line.status, effort_minutes=plan_item.effort_minutes)
        await record_status(db, plan_item, line.status, note=line.notes, user_id=user_id)

        mirror = EntryItem(
            entry_id=entry.id, plan_item_id=plan_item.id, sort_order=order,
            task_type_id=plan_item.task_type_id,
            question_type_id=plan_item.question_type_id,
            customer=plan_item.customer, count=line.count, notes=line.notes,
            due_at=line.due_at, status=line.status,
            effort_minutes=line.effort_minutes,
            jira_issue_key=plan_item.jira_issue_key,
            jira_issue_url=plan_item.jira_issue_url,
        )
        db.add(mirror)
        await db.flush()
        db.add(EntryItemStatusEvent(
            entry_item_id=mirror.id, to_status=line.status, source="web",
            note=line.notes, changed_by_user_id=user_id,
        ))
        order += 1

    for extra in data.extra_items:
        # A normal task like any other — it just wasn't on this morning's
        # list. Starts wherever the caller says (open, by default), and moves
        # the same way a planned one does.
        await _new_item(db, entry, extra, order, status_=extra.status, user_id=user_id)
        order += 1

    await db.commit()
    return await db.scalar(_loaded(select(DailyEntry).where(DailyEntry.id == entry.id)))


async def patch_item(
    db: AsyncSession, item_id: int, *, status_: str | None, count: int | None,
    notes: str | None, comment: str | None, due_at: date | None, user_id: str | None,
    effort_minutes: int | None = None, task_type_id: int | None = None,
) -> EntryItem:
    item = await db.get(EntryItem, item_id)
    if item is None:
        raise err(404, "not_found", "No such item.")

    if task_type_id is not None and task_type_id != item.task_type_id:
        if not await db.get(TaskType, task_type_id):
            raise err(422, "unknown_task_type", f"No task type with id {task_type_id}.")
        item.task_type_id = task_type_id

    # Applied before the transition check, so a status move that also supplies
    # this save's effort is judged on the value it's about to have, not the
    # one it's leaving behind.
    if count is not None:
        item.count = count
    if notes is not None:
        item.notes = notes
    if due_at is not None:
        item.due_at = due_at
    if effort_minutes is not None:
        item.effort_minutes = effort_minutes

    if status_ and status_ != item.status:
        check_transition(item.status, status_, effort_minutes=item.effort_minutes)
        # `comment` — not `notes` — is what a status change carries: a remark
        # about *this* transition, logged on the event and posted to Jira,
        # never overwriting the ticket's own Summary.
        await record_status(db, item, status_, note=comment, user_id=user_id)
        # The plan row and every update row pointing at it are one task shown
        # more than once — move them all, whichever end the change came from.
        # A system-driven mirror sync, not a user transition, so it doesn't
        # go through check_transition.
        root = item.plan_item_id or item.id
        siblings = await db.scalars(select(EntryItem).where(
            or_(EntryItem.id == root, EntryItem.plan_item_id == root)
        ))
        for sib in siblings:
            if sib.id != item.id:
                await record_status(db, sib, status_, source="system", user_id=user_id)

    await db.commit()
    return await db.scalar(select(EntryItem).where(EntryItem.id == item_id))


async def today_status(db: AsyncSession, on: date, viewer_member_id: int | None = None) -> dict:
    """Who has filed a plan today, and who has followed it with an update.

    Reports the people, not just counts — a number nobody can act on is worse
    than a name they can chase. `you` is computed here rather than inferred by
    the caller from absence in a list: admins were being left out of the team
    set, so "not listed as missing" silently read as "already planned".
    """
    planned = {
        m: (mid, e) for mid, m, e in await db.execute(
            select(DailyEntry.member_id, Member.display_name, DailyEntry.id)
            .join(Member, Member.id == DailyEntry.member_id)
            .where(DailyEntry.entry_date == on, DailyEntry.kind == "plan",
                   DailyEntry.source != "jira")
        )
    }
    updated = {
        m for (m,) in await db.execute(
            select(Member.display_name)
            .select_from(DailyEntry)
            .join(Member, Member.id == DailyEntry.member_id)
            .where(DailyEntry.entry_date == on, DailyEntry.kind == "update")
        )
    }
    # Everyone active plans their day, admins included.
    active = {
        m: mid for mid, m in await db.execute(
            select(Member.id, Member.display_name).where(Member.is_active.is_(True))
        )
    }

    done = sorted(n for n in planned if n in updated)
    pending = sorted(n for n in planned if n not in updated)
    no_plan = sorted(n for n in active if n not in planned)

    mine = next((n for n, mid in active.items() if mid == viewer_member_id), None)
    you = {
        "member_id": viewer_member_id,
        "member": mine,
        "planned": mine is not None and mine in planned,
        "updated": mine is not None and mine in updated,
        "plan_entry_id": planned[mine][1] if mine in planned else None,
    }
    return {
        "date": on.isoformat(),
        "planned": len(planned),
        "updated": len(done),
        "awaiting_update": [{"member_id": planned[n][0], "member": n} for n in pending],
        "no_plan_yet": [{"member_id": active[n], "member": n} for n in no_plan],
        "team_size": len(active),
        "you": you,
    }


async def members_without_a_plan(db: AsyncSession, on: date) -> list[Member]:
    """Active members with an email who haven't filed a plan today."""
    planned = select(DailyEntry.member_id).where(
        DailyEntry.entry_date == on, DailyEntry.kind == "plan", DailyEntry.source != "jira"
    )
    return list(await db.scalars(
        select(Member).where(
            Member.is_active.is_(True),
            Member.email.isnot(None),
            Member.id.notin_(planned),
        ).order_by(Member.display_name)
    ))


async def list_items(
    db: AsyncSession, *, frm: date, to: date, member_id: int | None = None,
    kind: str | None = None, status_: str | None = None, task_type_id: int | None = None,
    customer: str | None = None, pipeline: str | None = None, q: str | None = None,
    page: int = 1, page_size: int = 50,
) -> tuple[list, int]:
    """The work log, one row per ticket.

    Filtering and paging happen on items, not entries. Doing it per entry meant
    `status=closed` returned every entry containing one closed ticket — and
    still rendered its open ones — while the total counted days rather than
    rows. A backfilled day holds a dozen tickets, so the two were far apart.
    """
    if frm > to:
        raise err(422, "bad_range", "`from` is after `to`.")

    where = [DailyEntry.entry_date.between(frm, to)]
    if member_id:
        where.append(DailyEntry.member_id == member_id)
    if kind:
        where.append(DailyEntry.kind == kind)
    if status_:
        where.append(EntryItem.status == status_)
    if task_type_id:
        where.append(EntryItem.task_type_id == task_type_id)
    if pipeline:
        where.append(EntryItem.pipeline == pipeline)
    if customer:
        where.append(EntryItem.customer.ilike(f"%{customer}%"))
    if q:
        like = f"%{q}%"
        where.append(or_(
            EntryItem.notes.ilike(like),
            EntryItem.customer.ilike(like),
            EntryItem.jira_issue_key.ilike(like),
            TaskType.name.ilike(like),
            DailyEntry.raw_text.ilike(like),
        ))

    base = (
        select(EntryItem, DailyEntry)
        .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
        .join(TaskType, TaskType.id == EntryItem.task_type_id)
        .where(*where)
    )
    total = await db.scalar(
        select(func.count())
        .select_from(EntryItem)
        .join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
        .join(TaskType, TaskType.id == EntryItem.task_type_id)
        .where(*where)
    )
    rows = await db.execute(
        base.order_by(DailyEntry.entry_date.desc(), EntryItem.id.desc())
        .limit(page_size).offset((page - 1) * page_size)
    )
    return list(rows), total or 0


async def list_entries(
    db: AsyncSession, *, frm: date, to: date, member_id: int | None = None,
    kind: str | None = None, status_: str | None = None, task_type_id: int | None = None,
    customer: str | None = None, q: str | None = None, page: int = 1, page_size: int = 50,
) -> tuple[list[DailyEntry], int]:
    if frm > to:
        raise err(422, "bad_range", "`from` is after `to`.")

    where = [DailyEntry.entry_date.between(frm, to)]
    if member_id:
        where.append(DailyEntry.member_id == member_id)
    if kind:
        where.append(DailyEntry.kind == kind)
    if status_:
        where.append(DailyEntry.id.in_(
            select(EntryItem.entry_id).where(EntryItem.status == status_)
        ))
    if task_type_id:
        where.append(DailyEntry.id.in_(
            select(EntryItem.entry_id).where(EntryItem.task_type_id == task_type_id)
        ))
    if customer:
        where.append(DailyEntry.id.in_(
            select(EntryItem.entry_id).where(EntryItem.customer.ilike(f"%{customer}%"))
        ))
    if q:
        like = f"%{q}%"
        where.append(or_(
            DailyEntry.raw_text.ilike(like),
            DailyEntry.id.in_(
                select(EntryItem.entry_id)
                .join(TaskType, TaskType.id == EntryItem.task_type_id)
                .where(or_(
                    EntryItem.notes.ilike(like),
                    EntryItem.customer.ilike(like),
                    TaskType.name.ilike(like),
                ))
            ),
        ))

    total = await db.scalar(select(func.count()).select_from(DailyEntry).where(*where))
    rows = await db.scalars(
        _loaded(select(DailyEntry).where(*where))
        .order_by(DailyEntry.entry_date.desc(), DailyEntry.id.desc())
        .limit(page_size).offset((page - 1) * page_size)
    )
    return list(rows), total or 0
