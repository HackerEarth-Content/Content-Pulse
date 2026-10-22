"""Event Question Review service logic — the L1/L2 assignment and sign-off
state machine, and the audit trail behind it. Exercises `services/event_review`
directly against the real DB (this suite's convention, see conftest.py);
Redash itself is never called here since none of this logic reads it."""

import itertools

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update

from core.database import Session
from core.orm import Member, QuestionReview, QuestionReviewEvent
from schemas.event_review import (
    AssignIn,
    ClaimIn,
    L2SubmitIn,
    ReassignL2In,
    SubmitIn,
)
from services import event_review as svc

REVIEWER = "EQR PyTest Reviewer"
LEAD = "EQR PyTest Lead"
_next_id = itertools.count(900_000_001)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def cleanup_members():
    yield
    async with Session() as db:
        ids = (
            (
                await db.execute(
                    select(Member.id).where(Member.display_name.in_((REVIEWER, LEAD)))
                )
            )
            .scalars()
            .all()
        )
        if ids:
            await db.execute(
                update(Member).where(Member.id.in_(ids)).values(is_active=False)
            )
            await db.commit()


@pytest_asyncio.fixture
async def members():
    """A regular reviewer and a lead, both active."""
    async with Session() as db:
        out = {}
        for name, role in ((REVIEWER, "content"), (LEAD, "admin")):
            m = await db.scalar(select(Member).where(Member.display_name == name))
            if m is None:
                m = Member(display_name=name, role=role)
                db.add(m)
                await db.commit()
            m.role, m.is_active = role, True
            out[name] = m
        await db.commit()
        return {"reviewer": out[REVIEWER].id, "lead": out[LEAD].id}


@pytest_asyncio.fixture
async def qr():
    """A fresh QuestionReview row with a throwaway setter_template_id, wiped
    (along with its history events) once the test is done."""
    stid = next(_next_id)
    async with Session() as db:
        db.add(
            QuestionReview(setter_template_id=stid, question_type="MCQ", title="Test Q")
        )
        await db.commit()
    yield stid
    async with Session() as db:
        await db.execute(
            delete(QuestionReviewEvent).where(
                QuestionReviewEvent.setter_template_id == stid
            )
        )
        await db.execute(
            delete(QuestionReview).where(QuestionReview.setter_template_id == stid)
        )
        await db.commit()


def _member(id_, name):
    return Member(id=id_, display_name=name)


# ── schema validation ────────────────────────────────────────────────────────


def test_submit_requires_note_for_fixed_and_removed():
    with pytest.raises(ValueError):
        SubmitIn(event_slug="s", setter_template_ids=[1], status="fixed")
    with pytest.raises(ValueError):
        SubmitIn(event_slug="s", setter_template_ids=[1], status="removed", note="  ")
    SubmitIn(
        event_slug="s", setter_template_ids=[1], status="fixed", note="patched the tag"
    )


def test_submit_no_issue_found_needs_no_note():
    SubmitIn(event_slug="s", setter_template_ids=[1], status="no_issue_found")


# ── submit_verdict ────────────────────────────────────────────────────────────


async def test_submit_verdict_marks_l1_done(members, qr):
    actor = _member(members["reviewer"], REVIEWER)
    async with Session() as db:
        rows = await svc.submit_verdict(
            db,
            actor,
            SubmitIn(
                event_slug="ev-1", setter_template_ids=[qr], status="no_issue_found"
            ),
        )
    row = rows[0]
    assert row.l1_status == "done"
    assert row.last_verdict == "no_issue_found"
    assert row.l1_assignee.id == actor.id
    assert row.l1_comments == "No issue found."


# ── assign ────────────────────────────────────────────────────────────────────


async def test_assign_l2_before_l1_raises(members, qr):
    actor = _member(members["lead"], LEAD)
    async with Session() as db:
        with pytest.raises(svc.NeedsL1First):
            await svc.assign(
                db,
                actor,
                AssignIn(
                    setter_template_ids=[qr], member_id=members["reviewer"], level="l2"
                ),
            )


async def test_assign_l1_then_l2_succeeds(members, qr):
    actor = _member(members["lead"], LEAD)
    async with Session() as db:
        await svc.assign(
            db,
            actor,
            AssignIn(
                setter_template_ids=[qr], member_id=members["reviewer"], level="l1"
            ),
        )
        rows = await svc.assign(
            db,
            actor,
            AssignIn(setter_template_ids=[qr], member_id=members["lead"], level="l2"),
        )
    row = rows[0]
    assert row.l1_assignee.id == members["reviewer"]
    assert row.l2_assignee.id == members["lead"]
    assert row.l2_status == "pending"


# ── claim ─────────────────────────────────────────────────────────────────────


async def test_claim_l1_unassigned_is_self_assigned(members, qr):
    actor = _member(members["reviewer"], REVIEWER)
    async with Session() as db:
        row = await svc.claim(
            db, actor, ClaimIn(setter_template_id=qr, level="l1"), is_lead=False
        )
    assert row.l1_assignee.id == actor.id
    assert row.l1_status == "in_progress"


async def test_claim_l2_by_non_assignee_raises(members, qr):
    lead = _member(members["lead"], LEAD)
    reviewer = _member(members["reviewer"], REVIEWER)
    async with Session() as db:
        await svc.assign(
            db,
            lead,
            AssignIn(
                setter_template_ids=[qr], member_id=members["reviewer"], level="l1"
            ),
        )
        await svc.assign(
            db,
            lead,
            AssignIn(setter_template_ids=[qr], member_id=members["lead"], level="l2"),
        )
        with pytest.raises(svc.NotYourReview):
            await svc.claim(
                db, reviewer, ClaimIn(setter_template_id=qr, level="l2"), is_lead=False
            )
        # The assignee themself, and a lead acting on anyone's behalf, both succeed.
        row = await svc.claim(
            db, lead, ClaimIn(setter_template_id=qr, level="l2"), is_lead=False
        )
    assert row.l2_status == "in_progress"


# ── l2_submit ─────────────────────────────────────────────────────────────────


async def test_l2_submit_without_a_pending_review_raises(members, qr):
    # No L2 assignee yet, so a non-lead would fail the ownership check first
    # (see test_l2_submit_by_wrong_member_raises) — acting as a lead isolates
    # the status check this test is actually about.
    actor = _member(members["lead"], LEAD)
    async with Session() as db:
        with pytest.raises(svc.NotSubmittable):
            await svc.l2_submit(
                db,
                actor,
                L2SubmitIn(
                    setter_template_ids=[qr], verdict="no_issue_found", comment="ok"
                ),
                is_lead=True,
            )


async def test_l2_submit_by_wrong_member_raises(members, qr):
    lead = _member(members["lead"], LEAD)
    reviewer = _member(members["reviewer"], REVIEWER)
    async with Session() as db:
        await svc.assign(
            db,
            lead,
            AssignIn(
                setter_template_ids=[qr], member_id=members["reviewer"], level="l1"
            ),
        )
        await svc.assign(
            db,
            lead,
            AssignIn(setter_template_ids=[qr], member_id=members["lead"], level="l2"),
        )
        with pytest.raises(svc.NotYourReview):
            await svc.l2_submit(
                db,
                reviewer,
                L2SubmitIn(
                    setter_template_ids=[qr], verdict="no_issue_found", comment="ok"
                ),
                is_lead=False,
            )
        rows = await svc.l2_submit(
            db,
            lead,
            L2SubmitIn(
                setter_template_ids=[qr], verdict="no_issue_found", comment="looks good"
            ),
            is_lead=False,
        )
    row = rows[0]
    assert row.l2_status == "done"
    assert row.l2_comments == "looks good"
    assert row.l2_verdict == "no_issue_found"


# ── reassign + history ────────────────────────────────────────────────────────


async def test_reassign_l2_resets_status_and_history_records_both_levels(members, qr):
    lead = _member(members["lead"], LEAD)
    async with Session() as db:
        await svc.submit_verdict(
            db,
            lead,
            SubmitIn(
                event_slug="ev-1", setter_template_ids=[qr], status="no_issue_found"
            ),
        )
        await svc.assign(
            db,
            lead,
            AssignIn(setter_template_ids=[qr], member_id=members["lead"], level="l2"),
        )
        await svc.l2_submit(
            db,
            lead,
            L2SubmitIn(
                setter_template_ids=[qr], verdict="no_issue_found", comment="first pass"
            ),
            is_lead=False,
        )
        row = await svc.reassign_l2(
            db, lead, ReassignL2In(setter_template_id=qr, member_id=members["reviewer"])
        )
        hist = await svc.history(db, qr)

    assert row.l2_status == "pending"
    assert row.l2_comments is None
    assert row.l2_assignee.id == members["reviewer"]
    levels = [e.level for e in hist.entries]
    assert levels == ["l1", "l2"]
    assert hist.entries[0].verdict == "no_issue_found"
    assert hist.entries[1].by == LEAD


# ── L2 verdicts, bulk, and notifications ──────────────────────────────────────


def test_l2_submit_requires_comment_for_fixed_and_removed():
    for verdict in ("fixed", "removed"):
        with pytest.raises(ValueError):
            L2SubmitIn(setter_template_ids=[1], verdict=verdict, comment=" ")
    L2SubmitIn(setter_template_ids=[1], verdict="no_issue_found")


async def test_l2_verdict_becomes_last_verdict_and_bulk_submits(members, qr):
    lead = _member(members["lead"], LEAD)
    async with Session() as db:
        await svc.submit_verdict(
            db,
            lead,
            SubmitIn(
                event_slug="ev-1", setter_template_ids=[qr], status="fixed", note="typo"
            ),
        )
        await svc.assign(
            db,
            lead,
            AssignIn(setter_template_ids=[qr], member_id=members["lead"], level="l2"),
        )
        rows = await svc.l2_submit(
            db,
            lead,
            L2SubmitIn(setter_template_ids=[qr], verdict="removed", comment="dup"),
            is_lead=False,
        )
    assert rows[0].l2_verdict == "removed"
    assert rows[0].last_verdict == "removed"
    assert rows[0].removal_reason == "dup"
    assert rows[0].last_reviewed_by.id == members["lead"]


async def test_bulk_submit_limited_to_own_rows_for_non_leads(members, qr):
    lead = _member(members["lead"], LEAD)
    reviewer = _member(members["reviewer"], REVIEWER)
    other = next(_next_id)
    async with Session() as db:
        db.add(QuestionReview(setter_template_id=other))
        await db.commit()
        for stid in (qr, other):
            await svc.assign(
                db,
                lead,
                AssignIn(
                    setter_template_ids=[stid], member_id=members["lead"], level="l1"
                ),
            )
        payload = SubmitIn(
            event_slug="ev-1", setter_template_ids=[qr, other], status="no_issue_found"
        )
        with pytest.raises(svc.NotYourReview):
            await svc.submit_verdict(db, reviewer, payload, is_lead=False)
        rows = await svc.submit_verdict(db, lead, payload, is_lead=False)
    assert all(r.l1_status == "done" for r in rows)


async def test_assignment_posts_to_review_channel(members, qr, monkeypatch):
    sent = []

    async def fake(member, text):
        sent.append((member.id, text))
        return True

    monkeypatch.setattr(svc, "notify_review", fake)
    lead = _member(members["lead"], LEAD)
    async with Session() as db:
        await svc.assign(
            db,
            lead,
            AssignIn(
                setter_template_ids=[qr],
                member_id=members["reviewer"],
                level="l1",
                event_slug="ev-1",
            ),
        )
        # assigning yourself stays quiet
        await svc.assign(
            db,
            lead,
            AssignIn(setter_template_ids=[qr], member_id=members["lead"], level="l1"),
        )
    assert len(sent) == 1
    assert sent[0][0] == members["reviewer"]
    assert "L1 review of 1 question from" in sent[0][1] and "ev-1" in sent[0][1]
