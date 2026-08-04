from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from api.analytics_routes import scope
from core.database import get_session
from core.dates import resolve_range
from core.users import current_user
from services import analytics as an
from services import export

router = APIRouter(prefix="/api/exports", tags=["exports"],
                   dependencies=[Depends(current_user)])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _attachment(content: bytes | str, filename: str, media_type: str) -> Response:
    # RFC 5987 so names with non-ASCII survive the trip.
    return Response(
        content=content, media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


async def _filters(
    period: str | None = None,
    frm: date | None = Query(None, alias="from"),
    to: date | None = None,
    member_id: int | None = None,
    kind: str | None = Query(None, pattern="^(plan|update)$"),
    status: str | None = Query(None, pattern="^(open|in_progress|blocked|closed)$"),
    task_type_id: int | None = None,
    customer: str | None = None,
    q: str | None = None,
) -> dict:
    start, end = resolve_range(period, frm, to)
    return {"frm": start, "to": end, "member_id": member_id, "kind": kind,
            "status_": status, "task_type_id": task_type_id,
            "customer": customer, "q": q}


@router.get("/work-log.xlsx")
async def work_log_xlsx(filters: dict = Depends(_filters), db: AsyncSession = Depends(get_session)):
    content = await export.work_log_xlsx(db, **filters)
    return _attachment(content, f"work-log-{filters['frm']}_{filters['to']}.xlsx", XLSX)


@router.get("/work-log.csv")
async def work_log_csv(filters: dict = Depends(_filters), db: AsyncSession = Depends(get_session)):
    content = await export.work_log_csv(db, **filters)
    return _attachment(content, f"work-log-{filters['frm']}_{filters['to']}.csv", "text/csv")


@router.get("/ae-daily.xlsx")
async def ae_daily_xlsx(
    period: str | None = None,
    frm: date | None = Query(None, alias="from"),
    to: date | None = None,
    db: AsyncSession = Depends(get_session),
):
    start, end = resolve_range(period, frm, to)
    content = await export.ae_daily_xlsx(db, start, end)
    return _attachment(content, f"ae-daily-{start:%d%b%Y}_{end:%d%b%Y}.xlsx", XLSX)


@router.get("/content-requests.xlsx")
async def content_requests_xlsx(
    status: str | None = None,
    assignee: str | None = None,
    priority: str | None = None,
    issue_type: str | None = None,
    frm: date | None = Query(None, alias="from"),
    to: date | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_session),
):
    content = await export.content_requests_xlsx(
        db, status=status, assignee=assignee, priority=priority,
        issue_type=issue_type, frm=frm, to=to, q=q,
    )
    return _attachment(content, "content-requests.xlsx", XLSX)


@router.get("/analytics.xlsx")
async def analytics_xlsx(s: an.Scope = Depends(scope), db: AsyncSession = Depends(get_session)):
    content = await export.analytics_xlsx(db, s)
    return _attachment(content, f"analytics-{s.frm}_{s.to}.xlsx", XLSX)
