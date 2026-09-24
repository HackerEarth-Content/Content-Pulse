"""Event Question Review business logic — see EVENT_QUESTION_REVIEW.md.

Redash (query 5671) stays the source of truth for a library question's own
content (title, tags, level, ...) — every fetch re-reads it and refreshes the
cached copy in `question_reviews` — but that copy is also persisted, so it
survives a Redash outage and write endpoints can answer with full rows
without a round trip back to Redash. Keyed by `setter_template_id` since a
review belongs to the library question, not to whichever event pulled it in.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.orm import EventReviewSync, Member, QuestionReview, QuestionReviewEvent
from integrations import redash
from integrations.slack import notify_assignment
from schemas.event_review import (
    AssignIn,
    ClaimIn,
    EventReviewOut,
    EventReviewSummary,
    HistoryEntry,
    HistoryOut,
    L2SubmitIn,
    MemberRef,
    QuestionRow,
    ReassignL2In,
    RecentlyReviewed,
    SubmitIn,
)

log = logging.getLogger(__name__)

STALE_DAYS = 90
RECENT_DAYS = 7
QUERY_ID = redash.QUERIES["event_question_library"]["id"]

SLUG_PATTERNS = (
    re.compile(r"/recruiter/([a-z0-9-]+)/?", re.I),
    re.compile(r"/challenges/test/([a-z0-9-]+)/?", re.I),
)


def _now() -> datetime:
    """Naive UTC — matches this app's `timestamp without time zone` columns
    (see core/dates.py); a tz-aware value here can't be compared once it's
    round-tripped through Postgres and come back naive."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def extract_slug(text: str) -> str | None:
    """The two known HE URL shapes; falls through to treating the whole
    input as an already-pasted slug if neither pattern matches and it looks
    like one — the frontend's raw-slug fallback still works without this,
    but a slug pasted here shouldn't need the fallback box too."""
    text = text.strip()
    for pattern in SLUG_PATTERNS:
        if m := pattern.search(text):
            return m.group(1)
    if re.fullmatch(r"[a-z0-9-]+", text, re.I):
        return text
    return None


class EventReviewError(Exception):
    """Redash unreachable/disabled — the route turns this into a 502."""


async def _fetch_redash_rows(slug: str) -> list[dict]:
    try:
        client = redash._client()
    except redash.RedashDisabled as e:
        raise EventReviewError(str(e)) from e
    today = _now().date().isoformat()
    try:
        async with client as c:
            result = await redash.run_query(
                c, QUERY_ID, today, today, {"Event Slug": slug}
            )
    except redash.RedashError as e:
        raise EventReviewError(str(e)) from e

    # Same Setter Template ID can appear more than once (reused across
    # sections) — a review is per-template, so the first sighting wins.
    seen: dict[int, dict] = {}
    for row in result["rows"]:
        raw_stid = str(row.get("Setter Template ID") or "").strip()
        if not raw_stid:
            # Seen live: a "Copied from test" row with no Setter Template ID
            # at all. Not a library question a review can attach to — skip
            # it rather than let one bad row take down the whole event.
            log.warning(
                "event_question_library row with no Setter Template ID, skipped: %r",
                row.get("Title"),
            )
            continue
        stid = int(raw_stid)
        seen.setdefault(stid, row)
    return list(seen.values())


async def _members_by_id(db: AsyncSession, ids: set[int]) -> dict[int, Member]:
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    rows = await db.scalars(select(Member).where(Member.id.in_(ids)))
    return {m.id: m for m in rows}


def _ref(m: Member | None) -> MemberRef | None:
    return MemberRef(id=m.id, display_name=m.display_name) if m else None


def _to_row(qr: QuestionReview, members: dict[int, Member]) -> QuestionRow:
    stale = bool(
        qr.last_reviewed_at and (_now() - qr.last_reviewed_at).days >= STALE_DAYS
    )
    return QuestionRow(
        setter_template_id=qr.setter_template_id,
        question_type=qr.question_type,
        problem_id=qr.problem_id,
        title=qr.title,
        level=qr.level,
        tags=qr.tags,
        score=qr.score,
        description=qr.description,
        company=qr.company,
        section=qr.section,
        workspace=qr.workspace,
        created_by=qr.created_by,
        added_by=qr.added_by,
        library_type=qr.library_type,
        content_created_at=qr.content_created_at,
        last_verdict=qr.last_verdict,
        last_reviewed_at=qr.last_reviewed_at,
        last_reviewed_slug=qr.last_reviewed_slug,
        issue_summary=qr.issue_summary,
        removal_reason=qr.removal_reason,
        resurfaced_removed=qr.last_verdict == "removed",
        stale=stale,
        l1_assignee=_ref(members.get(qr.l1_assignee_id)) if qr.l1_assignee_id else None,
        l1_status=qr.l1_status,
        l1_comments=qr.l1_comments,
        l2_assignee=_ref(members.get(qr.l2_assignee_id)) if qr.l2_assignee_id else None,
        l2_status=qr.l2_status,
        l2_comments=qr.l2_comments,
    )


async def _rows_for(
    db: AsyncSession, reviews: list[QuestionReview]
) -> list[QuestionRow]:
    member_ids = {qr.l1_assignee_id for qr in reviews if qr.l1_assignee_id} | {
        qr.l2_assignee_id for qr in reviews if qr.l2_assignee_id
    }
    members = await _members_by_id(db, member_ids)
    return [_to_row(qr, members) for qr in reviews]


def _apply_redash_fields(qr: QuestionReview, row: dict, now: datetime) -> None:
    qr.question_type = row.get("QuestionType") or ""
    qr.problem_id = int(row.get("Problem ID") or 0)
    qr.title = row.get("Title") or ""
    qr.level = row.get("Level") or ""
    qr.tags = [t.strip() for t in (row.get("Tags") or "").split(",") if t.strip()]
    qr.score = int(row.get("Score") or 0)
    qr.description = row.get("Description") or ""
    qr.company = row.get("Company")
    qr.section = row.get("Section")
    qr.workspace = row.get("Workspace")
    qr.created_by = row.get("Created_By")
    qr.added_by = row.get("Added_By")
    qr.library_type = row.get("Library Type")
    qr.content_created_at = row.get("Created_At")
    qr.synced_at = now


async def get_event_review(db: AsyncSession, slug: str) -> EventReviewOut:
    sync = await db.get(EventReviewSync, slug)
    if sync is None:
        # First time seeing this slug — the only path that ever calls
        # Redash. Every later GET for the same slug is served entirely from
        # `question_reviews` (see EventReviewSync's docstring: no TTL, the
        # question set is treated as fixed once synced).
        redash_rows = await _fetch_redash_rows(slug)
        ids = [int(r["Setter Template ID"]) for r in redash_rows]
        reviews = await _get_or_create(db, ids)
        by_id = {qr.setter_template_id: qr for qr in reviews}
        now = _now()
        for redash_row in redash_rows:
            _apply_redash_fields(
                by_id[int(redash_row["Setter Template ID"])], redash_row, now
            )
        db.add(EventReviewSync(event_slug=slug, setter_template_ids=ids, synced_at=now))
        await db.commit()
    else:
        ids = sync.setter_template_ids
        reviews = await _get_or_create(db, ids)
        by_id = {qr.setter_template_id: qr for qr in reviews}

    member_ids = {qr.l1_assignee_id for qr in reviews if qr.l1_assignee_id} | {
        qr.l2_assignee_id for qr in reviews if qr.l2_assignee_id
    }
    members = await _members_by_id(db, member_ids)
    rows = [_to_row(by_id[stid], members) for stid in ids]

    cutoff = _now() - timedelta(days=RECENT_DAYS)
    recently_reviewed = [
        RecentlyReviewed(
            setter_template_id=row.setter_template_id,
            by=row.l1_assignee.display_name if row.l1_assignee else "—",
            at=row.last_reviewed_at,
        )
        for row in rows
        if row.last_reviewed_at and row.last_reviewed_at >= cutoff
    ]
    needs_review = sum(1 for row in rows if row.l1_status != "done")

    return EventReviewOut(
        event_slug=slug,
        rows=rows,
        summary=EventReviewSummary(
            needs_review_count=needs_review,
            reviewed_count=len(rows) - needs_review,
            recently_reviewed=recently_reviewed,
        ),
    )


async def _get_or_create(db: AsyncSession, ids: list[int]) -> list[QuestionReview]:
    existing = {
        qr.setter_template_id: qr
        for qr in await db.scalars(
            select(QuestionReview).where(QuestionReview.setter_template_id.in_(ids))
        )
    }
    out = []
    for stid in ids:
        qr = existing.get(stid)
        if qr is None:
            qr = QuestionReview(setter_template_id=stid)
            db.add(qr)
        out.append(qr)
    return out


async def submit_verdict(
    db: AsyncSession, actor: Member, payload: SubmitIn
) -> list[QuestionRow]:
    reviews = await _get_or_create(db, payload.setter_template_ids)
    now = _now()
    comment = payload.note or (
        "No issue found." if payload.status == "no_issue_found" else ""
    )

    for qr in reviews:
        qr.l1_assignee_id = qr.l1_assignee_id or actor.id
        qr.l1_status = "done"
        qr.l1_comments = comment
        qr.last_verdict = payload.status
        qr.last_reviewed_at = now
        qr.last_reviewed_slug = payload.event_slug
        qr.issue_summary = payload.note if payload.status == "fixed" else None
        qr.removal_reason = payload.note if payload.status == "removed" else None
        db.add(
            QuestionReviewEvent(
                setter_template_id=qr.setter_template_id,
                event_slug=payload.event_slug,
                level="l1",
                actor_member_id=actor.id,
                verdict=payload.status,
                note=comment,
            )
        )

    await db.commit()
    return await _rows_for(db, reviews)


class NeedsL1First(Exception):
    """L2 can't be assigned on a row nobody's L1-assigned yet."""


async def assign(
    db: AsyncSession, actor: Member, payload: AssignIn
) -> list[QuestionRow]:
    reviews = await _get_or_create(db, payload.setter_template_ids)
    member = (await _members_by_id(db, {payload.member_id})).get(payload.member_id)
    if member is None:
        raise ValueError("Unknown member")
    if payload.level == "l2" and any(qr.l1_assignee_id is None for qr in reviews):
        raise NeedsL1First()

    for qr in reviews:
        if payload.level == "l1":
            qr.l1_assignee_id = member.id
            qr.l1_status = "not_started"
        else:
            qr.l2_assignee_id = member.id
            qr.l2_status = "pending"
            qr.l2_comments = None
    await db.commit()

    if payload.level == "l2":
        await notify_assignment(
            member,
            actor.display_name,
            f"assigned you for L2 review of {len(reviews)} question(s).",
        )

    return await _rows_for(db, reviews)


async def claim(
    db: AsyncSession, actor: Member, payload: ClaimIn, is_lead: bool
) -> QuestionRow:
    qr = await db.get(QuestionReview, payload.setter_template_id)
    if qr is None:
        raise ValueError("Not found")
    if payload.level == "l1":
        # Unassigned L1 rows are fair game for anyone to claim — that's the
        # whole point of a soft claim signal. L2 is different: it's always
        # assigned to a specific person first, so starting it is that
        # person's call (or a lead's), not anyone who happens to open it.
        qr.l1_assignee_id = qr.l1_assignee_id or actor.id
        qr.l1_status = "in_progress"
    else:
        if qr.l2_assignee_id != actor.id and not is_lead:
            raise NotYourReview()
        qr.l2_status = "in_progress"
    await db.commit()
    return (await _rows_for(db, [qr]))[0]


class NotYourReview(Exception):
    """Caller isn't the assigned L2 reviewer (or a lead) — the route turns
    this into a 403, not a silent no-op or a write attributed to someone
    else."""


class NotSubmittable(Exception):
    """The question exists but has no L2 review in progress — a 409, not a
    404 (which would wrongly imply the question itself doesn't exist)."""


async def l2_submit(
    db: AsyncSession, actor: Member, payload: L2SubmitIn, is_lead: bool
) -> QuestionRow:
    qr = await db.get(QuestionReview, payload.setter_template_id)
    if qr is None:
        raise ValueError("Not found")
    if qr.l2_assignee_id != actor.id and not is_lead:
        raise NotYourReview()
    if qr.l2_status not in ("pending", "in_progress"):
        raise NotSubmittable()
    qr.l2_status = "done"
    qr.l2_comments = payload.comment
    db.add(
        QuestionReviewEvent(
            setter_template_id=qr.setter_template_id,
            event_slug=qr.last_reviewed_slug or "",
            level="l2",
            actor_member_id=actor.id,
            verdict=None,
            note=payload.comment,
        )
    )
    await db.commit()
    return (await _rows_for(db, [qr]))[0]


async def reassign_l2(
    db: AsyncSession, actor: Member, payload: ReassignL2In
) -> QuestionRow:
    qr = await db.get(QuestionReview, payload.setter_template_id)
    if qr is None:
        raise ValueError("Not found")
    member = (await _members_by_id(db, {payload.member_id})).get(payload.member_id)
    if member is None:
        raise ValueError("Unknown member")
    qr.l2_assignee_id = member.id
    qr.l2_status = "pending"
    qr.l2_comments = None
    await db.commit()
    await notify_assignment(
        member, actor.display_name, "re-assigned you for L2 review."
    )
    return (await _rows_for(db, [qr]))[0]


async def history(db: AsyncSession, setter_template_id: int) -> HistoryOut:
    rows = await db.execute(
        select(QuestionReviewEvent, Member.display_name)
        .join(Member, Member.id == QuestionReviewEvent.actor_member_id, isouter=True)
        .where(QuestionReviewEvent.setter_template_id == setter_template_id)
        .order_by(QuestionReviewEvent.created_at)
    )
    entries = [
        HistoryEntry(
            at=event.created_at,
            event_slug=event.event_slug,
            level=event.level,
            by=name or "—",
            verdict=event.verdict,
            note=event.note,
        )
        for event, name in rows
    ]
    return HistoryOut(setter_template_id=setter_template_id, entries=entries)
