from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.deps import ADMINS, require_role
from core.orm import McqReviewJob, User
from core.users import current_user
from schemas.mcq_review import McqReviewJobDetail, McqReviewJobSummary
from schemas.taxonomy import TaxonomyGroup, TaxonomyTagIn, TaxonomyTagOut
from services import mcq_reviewer as svc
from services import taxonomy as taxonomy_svc

router = APIRouter(
    prefix="/api/utils", tags=["utils"], dependencies=[Depends(current_user)]
)
admin_only = Depends(require_role(*ADMINS))

RECENT_JOBS_LIMIT = 20


@router.post("/mcq-reviewer", response_model=McqReviewJobSummary, status_code=201)
async def upload_mcq_reviewer(
    background: BackgroundTasks,
    file: UploadFile,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    content = await file.read()
    job = McqReviewJob(
        user_id=user.id, filename=file.filename or "upload", status="uploaded"
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
