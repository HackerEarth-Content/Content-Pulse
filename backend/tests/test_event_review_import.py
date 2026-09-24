"""Admin data import for Event Question Review — the preview/confirm split,
conflict detection (never silently overwrite an already-reviewed question),
and re-import idempotency (no duplicate history rows). See
services/event_review_import.py and EVENT_QUESTION_REVIEW.md.

Exercises `process_workbook`/`run_validation`/`run_import` directly rather
than through HTTP + BackgroundTasks — deterministic, and this suite's other
service-level tests (test_event_review.py) use the same approach."""

import io
import itertools

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from sqlalchemy import delete, select, update

from core.database import Session
from core.orm import (
    EventReviewImportJob,
    Member,
    QuestionReview,
    QuestionReviewEvent,
    User,
)
from core.users import current_user
from main import app
from services import event_review_import as svc

REVIEWER = "EQR Import PyTest Reviewer"
_next_id = itertools.count(900_100_001)
SLUG = "import-pytest-event"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def cleanup_reviewer():
    yield
    async with Session() as db:
        await db.execute(
            update(Member)
            .where(Member.display_name == REVIEWER)
            .values(is_active=False)
        )
        await db.commit()


@pytest_asyncio.fixture
async def reviewer_id():
    async with Session() as db:
        m = await db.scalar(select(Member).where(Member.display_name == REVIEWER))
        if m is None:
            m = Member(display_name=REVIEWER, role="content")
            db.add(m)
        m.is_active = True
        await db.commit()
        return m.id


@pytest_asyncio.fixture
async def stid():
    """A fresh Setter Template ID, wiped before and after."""
    stid = next(_next_id)
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


def _xlsx(
    stid: int,
    *,
    l1_status="GTG",
    l1_comment="Looks fine",
    drop_column: str | None = None,
) -> bytes:
    header = [
        "QuestionType",
        "Problem ID",
        "Setter Template ID",
        "Title",
        "Level",
        "Tags",
        "Score",
        "Description",
        "L1 reviewer",
        "L1 review status",
        "L1 review comments",
        "L2 reviewer",
        "L2 review status",
        "L2 review comments",
    ]
    row = [
        "Multiple Choice Questions",
        800001,
        stid,
        "Import test question",
        "Easy",
        "Tag1,Tag2",
        4,
        "An import-test question.",
        REVIEWER,
        l1_status,
        l1_comment,
        "",
        "",
        "",
    ]
    if drop_column:
        idx = header.index(drop_column)
        del header[idx]
        del row[idx]

    wb = Workbook()
    ws = wb.active
    ws.title = SLUG
    ws.append(header)
    ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def test_dry_run_previews_without_writing(reviewer_id, stid):
    async with Session() as db:
        preview = await svc.process_workbook(db, _xlsx(stid), dry_run=True)
        await db.commit()
        qr = await db.get(QuestionReview, stid)

    assert qr is None, "a dry run must never write to the DB"
    assert preview["dry_run"] is True
    assert preview["total_questions"] == 1
    assert preview["total_reviews"] == 1
    assert preview["total_conflicts"] == 0
    assert preview["sheets"][0]["slug"] == SLUG


async def test_confirmed_import_writes_review_and_history(reviewer_id, stid):
    async with Session() as db:
        result = await svc.process_workbook(db, _xlsx(stid), dry_run=False)
        await db.commit()
        qr = await db.get(QuestionReview, stid)
        events = (
            await db.scalars(
                select(QuestionReviewEvent).where(
                    QuestionReviewEvent.setter_template_id == stid
                )
            )
        ).all()

    assert result["total_reviews"] == 1
    assert qr.l1_status == "done"
    assert qr.last_verdict == "no_issue_found"
    assert qr.l1_assignee_id == reviewer_id
    assert len(events) == 1
    assert events[0].level == "l1"


async def test_reimporting_the_same_file_does_not_duplicate_history(reviewer_id, stid):
    async with Session() as db:
        await svc.process_workbook(db, _xlsx(stid), dry_run=False)
        await db.commit()
    async with Session() as db:
        await svc.process_workbook(db, _xlsx(stid), dry_run=False)
        await db.commit()
        events = (
            await db.scalars(
                select(QuestionReviewEvent).where(
                    QuestionReviewEvent.setter_template_id == stid
                )
            )
        ).all()

    assert len(events) == 1, "an identical re-import must not insert a duplicate event"


async def test_conflicting_row_is_skipped_not_overwritten(reviewer_id, stid):
    async with Session() as db:
        db.add(
            QuestionReview(
                setter_template_id=stid,
                title="Original title",
                l1_status="done",
                last_verdict="fixed",
                l1_comments="Already reviewed by someone else",
            )
        )
        await db.commit()

    async with Session() as db:
        result = await svc.process_workbook(
            db,
            _xlsx(stid, l1_status="Fixed", l1_comment="A completely different fix"),
            dry_run=False,
        )
        await db.commit()
        qr = await db.get(QuestionReview, stid)

    assert result["total_conflicts"] == 1
    assert result["conflicts"][0]["levels"] == ["l1"]
    assert qr.title == "Original title", (
        "a conflicting row must be skipped entirely, including content fields"
    )
    assert qr.l1_comments == "Already reviewed by someone else"


async def test_missing_required_column_is_reported_not_fatal(reviewer_id, stid):
    async with Session() as db:
        preview = await svc.process_workbook(
            db, _xlsx(stid, drop_column="Description"), dry_run=True
        )

    assert "Description" in preview["sheets"][0]["missing_columns"]
    assert preview["total_questions"] == 1, (
        "a missing optional-for-parsing column doesn't block the row"
    )


async def test_unmapped_status_is_warned_and_left_unset(reviewer_id, stid):
    async with Session() as db:
        result = await svc.process_workbook(
            db, _xlsx(stid, l1_status="Needs rework"), dry_run=False
        )
        await db.commit()
        qr = await db.get(QuestionReview, stid)

    assert any("unmapped L1 review status" in w for w in result["warnings"])
    assert qr is None or qr.l1_status == "not_started"


async def test_job_lifecycle_validate_then_confirm(reviewer_id, stid):
    content = _xlsx(stid)
    async with Session() as db:
        job = EventReviewImportJob(
            filename="test.xlsx", status="uploaded", source_file=content
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    await svc.run_validation(job_id, content)
    async with Session() as db:
        job = await db.get(EventReviewImportJob, job_id)
        assert job.status == "ready_for_review"
        assert job.preview["total_reviews"] == 1

    # A confirm attempt is meaningless before the preview is ready — the
    # route itself guards this (409), but run_import is also a no-op if
    # called out of turn, so it can never be reached with stale state.
    async with Session() as db:
        job = await db.get(EventReviewImportJob, job_id)
        job.status = "uploaded"
        await db.commit()
    await svc.run_import(job_id)
    async with Session() as db:
        job = await db.get(EventReviewImportJob, job_id)
        assert job.status == "uploaded", (
            "run_import must refuse to act unless ready_for_review"
        )

    async with Session() as db:
        job = await db.get(EventReviewImportJob, job_id)
        job.status = "ready_for_review"
        await db.commit()
    await svc.run_import(job_id)
    async with Session() as db:
        job = await db.get(EventReviewImportJob, job_id)
        assert job.status == "done"
        assert job.result["total_reviews"] == 1
        qr = await db.get(QuestionReview, stid)
        assert qr.l1_status == "done"

    async with Session() as db:
        await db.execute(
            delete(EventReviewImportJob).where(EventReviewImportJob.id == job_id)
        )
        await db.commit()


# ── over HTTP — route wiring, auth, and that BackgroundTasks really run ──────


async def test_non_admin_cannot_upload():
    """`client` (from conftest) is always admin-linked, so this exercises its
    own unlinked, no-superadmin user to actually hit the non-admin path."""
    async with Session() as db:
        user = await db.get(User, "eqr-import-outsider")
        if user is None:
            user = User(
                id="eqr-import-outsider",
                email="eqr-import-outsider@example.com",
                hashed_password="",
                is_verified=True,
            )
            db.add(user)
            await db.commit()

    app.dependency_overrides[current_user] = lambda: user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/api/utils/event-review/import",
                files={
                    "file": (
                        "t.xlsx",
                        _xlsx(next(_next_id)),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
            assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()


async def test_admin_upload_preview_confirm_round_trip(client, reviewer_id, stid):
    r = await client.post(
        "/api/utils/event-review/import",
        files={
            "file": (
                "t.xlsx",
                _xlsx(stid),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r.status_code == 201
    job_id = r.json()["id"]

    r = await client.get(f"/api/utils/event-review/import/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready_for_review", (
        "BackgroundTasks should already have run validation under the test transport"
    )
    assert body["preview"]["total_reviews"] == 1

    r = await client.post(f"/api/utils/event-review/import/{job_id}/confirm")
    assert r.status_code == 200

    r = await client.get(f"/api/utils/event-review/import/{job_id}")
    body = r.json()
    assert body["status"] == "done"
    assert body["result"]["total_reviews"] == 1

    async with Session() as db:
        qr = await db.get(QuestionReview, stid)
        assert qr.l1_status == "done"
        await db.execute(
            delete(EventReviewImportJob).where(EventReviewImportJob.id == job_id)
        )
        await db.commit()


async def test_confirm_before_preview_ready_is_refused(client):
    async with Session() as db:
        job = EventReviewImportJob(filename="t.xlsx", status="uploaded")
        db.add(job)
        await db.commit()
        job_id = job.id

    r = await client.post(f"/api/utils/event-review/import/{job_id}/confirm")
    assert r.status_code == 409

    async with Session() as db:
        await db.execute(
            delete(EventReviewImportJob).where(EventReviewImportJob.id == job_id)
        )
        await db.commit()
