from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.dates import resolve_range
from core.orm import DailyEntry, EntryItem, EntryItemStatusEvent, User
from core.users import current_user
from integrations import jira, slack
from schemas.entries import (
    EntryOut,
    ItemOut,
    ItemPatch,
    Page,
    PlanIn,
    StatusEventOut,
    UpdateIn,
)
from services import entries as svc

router = APIRouter(prefix="/api", tags=["entries"], dependencies=[Depends(current_user)])


@router.get("/entries", response_model=Page[EntryOut])
async def list_entries(
    period: str | None = None,
    frm: date | None = Query(None, alias="from"),
    to: date | None = None,
    member_id: int | None = None,
    kind: str | None = Query(None, pattern="^(plan|update)$"),
    status: str | None = Query(None, pattern="^(open|in_progress|blocked|closed)$"),
    task_type_id: int | None = None,
    customer: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
):
    frm, to = resolve_range(period, frm, to)
    rows, total = await svc.list_entries(
        db, frm=frm, to=to, member_id=member_id, kind=kind, status_=status,
        task_type_id=task_type_id, customer=customer, q=q, page=page, page_size=page_size,
    )
    return Page(items=[EntryOut.of(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/entries/plan", response_model=EntryOut)
async def get_plan(member_id: int, on: date, db: AsyncSession = Depends(get_session)):
    """Prefills the update form. 404 `no_plan` is expected, not an error — the
    UI offers 'log as extra work' instead."""
    plan = await svc.get_plan(db, member_id, on)
    if plan is None:
        raise svc.err(404, "no_plan", "No plan for this member and date.")
    return EntryOut.of(plan)


@router.get("/entries/{entry_id}", response_model=EntryOut)
async def get_entry(entry_id: int, db: AsyncSession = Depends(get_session)):
    entry = await db.scalar(svc._loaded(select(DailyEntry).where(DailyEntry.id == entry_id)))
    if entry is None:
        raise svc.err(404, "not_found", "No such entry.")
    return EntryOut.of(entry)


@router.post("/entries/plans", response_model=EntryOut, status_code=201)
async def create_plan(data: PlanIn, background: BackgroundTasks,
                      db: AsyncSession = Depends(get_session),
                      user: User = Depends(current_user)):
    entry = await svc.create_plan(db, data, user.id)
    await _dispatch(db, background, entry)
    return EntryOut.of(entry)


@router.post("/entries/updates", response_model=EntryOut, status_code=201)
async def create_update(data: UpdateIn, background: BackgroundTasks,
                        db: AsyncSession = Depends(get_session),
                        user: User = Depends(current_user)):
    entry = await svc.create_update(db, data, user.id)
    await _dispatch(db, background, entry)
    return EntryOut.of(entry)


async def _dispatch(db: AsyncSession, background: BackgroundTasks, entry) -> None:
    """Queue the integration work for after the response. A slow or broken Jira
    must never make saving a plan slow or look broken."""
    for item in entry.items:
        if item.jira_issue_key:
            background.add_task(jira.push_status, item.id, item.status, item.notes)
        else:
            item.jira_state = "pending"
            background.add_task(jira.push_item, item.id)
    await db.commit()
    background.add_task(slack.post_entry, entry.id)


@router.get("/entries/{entry_id}/jira-state")
async def jira_state(entry_id: int, db: AsyncSession = Depends(get_session)):
    """Polled by the form until nothing is `pending`."""
    rows = await db.scalars(select(EntryItem).where(EntryItem.entry_id == entry_id))
    items = [{"id": i.id, "jira_state": i.jira_state, "jira_issue_key": i.jira_issue_key,
              "jira_issue_url": i.jira_issue_url, "jira_error": i.jira_error} for i in rows]
    return {"items": items, "pending": any(i["jira_state"] == "pending" for i in items)}


@router.post("/entry-items/{item_id}/jira")
async def retry_jira(item_id: int, background: BackgroundTasks):
    """Retry one failed Jira write, without touching its siblings."""
    background.add_task(jira.push_item, item_id)
    return {"queued": True}


@router.patch("/entry-items/{item_id}", response_model=ItemOut)
async def patch_item(item_id: int, patch: ItemPatch, background: BackgroundTasks,
                     db: AsyncSession = Depends(get_session),
                     user: User = Depends(current_user)):
    item = await svc.patch_item(
        db, item_id, status_=patch.status, count=patch.count,
        notes=patch.notes, due_at=patch.due_at, user_id=user.id,
        effort_minutes=patch.effort_minutes,
    )
    if patch.status and item.jira_issue_key:
        background.add_task(jira.push_status, item.id, item.status, patch.notes)
    return ItemOut.of(item)


@router.get("/entry-items/{item_id}/history", response_model=list[StatusEventOut])
async def item_history(item_id: int, db: AsyncSession = Depends(get_session)):
    rows = await db.scalars(
        select(EntryItemStatusEvent)
        .where(EntryItemStatusEvent.entry_item_id == item_id)
        .order_by(EntryItemStatusEvent.changed_at)
    )
    return list(rows)


@router.delete("/entries/{entry_id}", status_code=204)
async def delete_entry(entry_id: int, db: AsyncSession = Depends(get_session)):
    """Items cascade. Any Jira issues stay — deleting a log row shouldn't
    silently delete someone's ticket."""
    entry = await db.get(DailyEntry, entry_id)
    if entry is None:
        raise svc.err(404, "not_found", "No such entry.")
    await db.delete(entry)
    await db.commit()
