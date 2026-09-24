from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Response,
    UploadFile,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from core.database import get_session
from core.deps import ADMINS, Viewer, get_viewer, require_role
from core.orm import EventReviewImportJob, McqReviewJob, Member, User
from core.users import current_user
from schemas.event_review import (
    AssignIn,
    ClaimIn,
    EventReviewOut,
    HistoryOut,
    ImportJobOut,
    L2SubmitIn,
    QuestionRow,
    ReassignL2In,
    SubmitIn,
)
from schemas.mcq_review import MCQReviewResult, McqReviewJobDetail, McqReviewJobSummary
from schemas.taxonomy import TaxonomyGroup, TaxonomyTagIn, TaxonomyTagOut
from services import event_review as eqr_svc
from services import event_review_import as eqr_import_svc
from services import export as export_svc
from services import mcq_reviewer as svc
from services import taxonomy as taxonomy_svc

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(
    prefix="/api/utils", tags=["utils"], dependencies=[Depends(current_user)]
)
admin_only = Depends(require_role(*ADMINS))

RECENT_JOBS_LIMIT = 20


def _viewer_member(viewer: Viewer) -> Member:
    if viewer.member is None:
        raise HTTPException(
            403,
            {
                "code": "no_member",
                "detail": "Your account isn't linked to a team member.",
            },
        )
    return viewer.member


@router.post("/mcq-reviewer", response_model=McqReviewJobSummary, status_code=201)
async def upload_mcq_reviewer(
    background: BackgroundTasks,
    file: UploadFile,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    content = await file.read()
    job = McqReviewJob(
        user_id=user.id,
        filename=file.filename or "upload",
        status="uploaded",
        source_file=content,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background.add_task(svc.run_review_job, job.id, content)
    return job


@router.get("/mcq-reviewer", response_model=list[McqReviewJobSummary])
async def list_my_mcq_reviewer_jobs(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    """The recent-jobs list — a job's URL alone isn't the only way back to it;
    this covers a lost/never-copied link too."""
    rows = await db.scalars(
        select(McqReviewJob)
        .where(McqReviewJob.user_id == user.id)
        .order_by(McqReviewJob.created_at.desc())
        .limit(RECENT_JOBS_LIMIT)
    )
    return list(rows)


@router.get("/mcq-reviewer/{job_id}", response_model=McqReviewJobDetail)
async def get_mcq_reviewer_job(
    job_id: int,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    job = await db.get(McqReviewJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(404, {"code": "not_found", "detail": "Job not found."})
    return job


@router.get("/mcq-reviewer/{job_id}/download")
async def download_mcq_reviewer_job(
    job_id: int,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    job = await db.scalar(
        select(McqReviewJob)
        .options(undefer(McqReviewJob.source_file))
        .where(McqReviewJob.id == job_id)
    )
    if job is None or job.user_id != user.id:
        raise HTTPException(404, {"code": "not_found", "detail": "Job not found."})
    if job.status != "done" or job.result is None or job.source_file is None:
        raise HTTPException(
            409, {"code": "not_ready", "detail": "This review isn't finished yet."}
        )

    result = MCQReviewResult.model_validate(job.result)
    content = svc.build_reviewed_workbook(job.source_file, job.filename, result)
    stem = job.filename.rsplit(".", 1)[0]
    return Response(
        content=content,
        media_type=XLSX,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''reviewed-{stem}.xlsx"
        },
    )


@router.get("/taxonomy", response_model=list[TaxonomyGroup])
async def list_taxonomy(db: AsyncSession = Depends(get_session)):
    rows = await taxonomy_svc.list_taxonomy(db)
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row.category, []).append(row)
    return [TaxonomyGroup(category=c, tags=tags) for c, tags in grouped.items()]


@router.post(
    "/taxonomy",
    response_model=TaxonomyTagOut,
    status_code=201,
    dependencies=[admin_only],
)
async def add_taxonomy_tag(
    body: TaxonomyTagIn, db: AsyncSession = Depends(get_session)
):
    return await taxonomy_svc.add_tag(db, body.category, body.tag)


@router.delete("/taxonomy/{tag_id}", status_code=204, dependencies=[admin_only])
async def remove_taxonomy_tag(tag_id: int, db: AsyncSession = Depends(get_session)):
    await taxonomy_svc.remove_tag(db, tag_id)


# ── event question review ────────────────────────────────────────────────────


@router.get("/event-review/{slug}", response_model=EventReviewOut)
async def get_event_review(slug: str, db: AsyncSession = Depends(get_session)):
    try:
        return await eqr_svc.get_event_review(db, slug)
    except eqr_svc.EventReviewError as e:
        raise HTTPException(502, {"code": "redash_unreachable", "detail": str(e)})


@router.post("/event-review/submit", response_model=list[QuestionRow])
async def submit_event_review(
    body: SubmitIn,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    actor = _viewer_member(viewer)
    if len(body.setter_template_ids) > 1 and not viewer.is_lead:
        raise HTTPException(
            403, {"code": "wrong_role", "detail": "Bulk submit is admin-only."}
        )
    return await eqr_svc.submit_verdict(db, actor, body)


@router.post("/event-review/assign", response_model=list[QuestionRow])
async def assign_event_review(
    body: AssignIn,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    actor = _viewer_member(viewer)
    self_assign = len(body.setter_template_ids) == 1 and body.member_id == actor.id
    if not self_assign and not viewer.is_lead:
        raise HTTPException(
            403,
            {
                "code": "wrong_role",
                "detail": "Assigning someone else, or assigning in bulk, is admin-only.",
            },
        )
    try:
        return await eqr_svc.assign(db, actor, body)
    except eqr_svc.NeedsL1First:
        raise HTTPException(
            409,
            {
                "code": "needs_l1_first",
                "detail": "Assign an L1 reviewer before assigning L2.",
            },
        )
    except ValueError:
        raise HTTPException(404, {"code": "not_found", "detail": "Unknown member."})


@router.post("/event-review/claim", response_model=QuestionRow)
async def claim_event_review(
    body: ClaimIn,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    actor = _viewer_member(viewer)
    try:
        return await eqr_svc.claim(db, actor, body, is_lead=viewer.is_lead)
    except eqr_svc.NotYourReview:
        raise HTTPException(
            403,
            {
                "code": "wrong_role",
                "detail": "Only the assigned L2 reviewer can start this.",
            },
        )
    except ValueError:
        raise HTTPException(404, {"code": "not_found", "detail": "Question not found."})


@router.post("/event-review/l2-submit", response_model=QuestionRow)
async def l2_submit_event_review(
    body: L2SubmitIn,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    actor = _viewer_member(viewer)
    try:
        return await eqr_svc.l2_submit(db, actor, body, is_lead=viewer.is_lead)
    except eqr_svc.NotYourReview:
        raise HTTPException(
            403,
            {
                "code": "wrong_role",
                "detail": "Only the assigned L2 reviewer can submit.",
            },
        )
    except eqr_svc.NotSubmittable:
        raise HTTPException(
            409,
            {
                "code": "not_submittable",
                "detail": "No L2 review is in progress for this question.",
            },
        )
    except ValueError:
        raise HTTPException(404, {"code": "not_found", "detail": "Question not found."})


@router.post(
    "/event-review/reassign-l2", response_model=QuestionRow, dependencies=[admin_only]
)
async def reassign_l2_event_review(
    body: ReassignL2In,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    actor = _viewer_member(viewer)
    try:
        return await eqr_svc.reassign_l2(db, actor, body)
    except ValueError:
        raise HTTPException(
            404, {"code": "not_found", "detail": "Question or member not found."}
        )


@router.get(
    "/event-review/history/{setter_template_id}",
    response_model=HistoryOut,
    dependencies=[admin_only],
)
async def event_review_history(
    setter_template_id: int, db: AsyncSession = Depends(get_session)
):
    return await eqr_svc.history(db, setter_template_id)


@router.get("/event-review/{slug}/export.xlsx")
async def export_event_review(slug: str, db: AsyncSession = Depends(get_session)):
    try:
        content = await export_svc.event_review_xlsx(db, slug)
    except eqr_svc.EventReviewError as e:
        raise HTTPException(502, {"code": "redash_unreachable", "detail": str(e)})
    return Response(
        content=content,
        media_type=XLSX,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''event-review-{slug}.xlsx"
        },
    )


# ── event question review: admin data import ─────────────────────────────────
# Two-phase, mirroring the reference seed script but additive (never
# truncates) and conflict-safe (never overwrites an already-reviewed
# question) — see services/event_review_import.py.


@router.post(
    "/event-review/import",
    response_model=ImportJobOut,
    status_code=201,
    dependencies=[admin_only],
)
async def upload_event_review_import(
    background: BackgroundTasks,
    file: UploadFile,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(
            400, {"code": "bad_file_type", "detail": "Upload a .xlsx workbook."}
        )
    content = await file.read()
    job = EventReviewImportJob(
        user_id=user.id,
        filename=file.filename or "upload",
        status="uploaded",
        source_file=content,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background.add_task(eqr_import_svc.run_validation, job.id, content)
    return job


@router.get(
    "/event-review/import/{job_id}",
    response_model=ImportJobOut,
    dependencies=[admin_only],
)
async def get_event_review_import(job_id: int, db: AsyncSession = Depends(get_session)):
    job = await db.get(EventReviewImportJob, job_id)
    if job is None:
        raise HTTPException(
            404, {"code": "not_found", "detail": "Import job not found."}
        )
    return job


@router.post(
    "/event-review/import/{job_id}/confirm",
    response_model=ImportJobOut,
    dependencies=[admin_only],
)
async def confirm_event_review_import(
    job_id: int, background: BackgroundTasks, db: AsyncSession = Depends(get_session)
):
    job = await db.get(EventReviewImportJob, job_id)
    if job is None:
        raise HTTPException(
            404, {"code": "not_found", "detail": "Import job not found."}
        )
    if job.status != "ready_for_review":
        raise HTTPException(
            409,
            {
                "code": "not_ready",
                "detail": "This import isn't ready to confirm yet (or was already confirmed).",
            },
        )
    background.add_task(eqr_import_svc.run_import, job.id)
    return job
