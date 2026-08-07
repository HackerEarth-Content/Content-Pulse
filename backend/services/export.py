"""XLSX and CSV builders.

Every cell of user-entered text goes through `safe()`. Notes and customer names
are free text that lands in a spreadsheet, and Excel executes any cell starting
with = + - @ — the Django exports wrote those raw.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.ext.asyncio import AsyncSession

from core.orm import STATUSES
from services import content_requests as cr_svc
from services import entries as entries_svc

MAX_ROWS = 20_000

HEAD_FILL = PatternFill("solid", fgColor="0F1620")
HEAD_FONT = Font(name="Calibri", bold=True, color="4FFFB0", size=10)
NAME_FILL = PatternFill("solid", fgColor="162032")
NAME_FONT = Font(name="Calibri", bold=True, color="9ECFFF", size=10)
DATE_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
BODY_FONT = Font(name="Calibri", size=10)
BOLD_FONT = Font(name="Calibri", size=10, bold=True)
STRIPE = PatternFill("solid", fgColor="0C1117")
RULE = Border(bottom=Side(style="thin", color="1A2535"))

STATUS_LABEL = {"open": "Open", "in_progress": "In Progress",
                "blocked": "Blocked", "closed": "Done"}

_RISKY = re.compile(r"^[=+\-@\t\r]")


def safe(value):
    """Neutralise spreadsheet formula injection. A note like
    `=HYPERLINK("http://evil","click")` is a live formula in Excel, not text."""
    if isinstance(value, str) and _RISKY.match(value):
        return "'" + value
    return value


def _header(ws, headers: list[str], widths: list[int], freeze: str = "A2") -> None:
    for col, (label, width) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=1, column=col, value=label)
        cell.fill, cell.font, cell.border = HEAD_FILL, HEAD_FONT, RULE
        cell.alignment = Alignment(horizontal="left", vertical="center")
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 20
    ws.freeze_panes = freeze


def _body(ws, rows: list[list], wrap_col: int | None = None) -> None:
    for r, values in enumerate(rows, 2):
        for c, value in enumerate(values, 1):
            cell = ws.cell(row=r, column=c, value=safe(value))
            cell.font, cell.border = BODY_FONT, RULE
            cell.alignment = Alignment(vertical="center", wrap_text=(c == wrap_col))
            if r % 2 == 0:
                cell.fill = STRIPE


def _save(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── work log ──────────────────────────────────────────────────────────────────

WORK_LOG_HEADERS = ["Date", "Kind", "Member", "Task Type", "Question Type",
                    "Customer", "Count", "Effort (min)", "Status", "Due", "Jira", "Notes"]


async def _work_log_rows(db: AsyncSession, **filters) -> tuple[list[list], bool]:
    entries, total = await entries_svc.list_entries(
        db, page=1, page_size=MAX_ROWS, **filters
    )
    rows = []
    for e in entries:
        if not e.items:
            rows.append([e.entry_date.isoformat(), e.kind.title(), e.member.display_name,
                         "", "", "", "", "", STATUS_LABEL.get(e.status, e.status), "", "",
                         e.raw_text or ""])
        rows.extend(
            [e.entry_date.isoformat(), e.kind.title(), e.member.display_name,
             it.task_type.name, it.question_type.name if it.question_type else "",
             it.customer or "", it.count or "", it.effort_minutes or "",
             STATUS_LABEL.get(it.status, it.status),
             it.due_at.isoformat() if it.due_at else "", it.jira_issue_key or "",
             it.notes or e.raw_text or ""]
            for it in e.items
        )
    return rows, total > len(entries)


async def work_log_xlsx(db: AsyncSession, **filters) -> bytes:
    rows, truncated = await _work_log_rows(db, **filters)
    wb = Workbook()
    ws = wb.active
    ws.title = "Work Log"
    _header(ws, WORK_LOG_HEADERS, [12, 8, 20, 28, 16, 18, 7, 11, 12, 12, 14, 50])
    _body(ws, rows, wrap_col=12)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(WORK_LOG_HEADERS))}1"
    if truncated:
        ws.cell(row=len(rows) + 3, column=1,
                value=f"Truncated at {MAX_ROWS} entries — narrow the date range.").font = BOLD_FONT
    return _save(wb)


async def work_log_csv(db: AsyncSession, **filters) -> str:
    rows, truncated = await _work_log_rows(db, **filters)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(WORK_LOG_HEADERS)
    w.writerows([[safe(v) for v in row] for row in rows])
    if truncated:
        w.writerow([f"Truncated at {MAX_ROWS} entries"])
    return buf.getvalue()


# ── content requests ──────────────────────────────────────────────────────────


async def content_requests_xlsx(db: AsyncSession, **filters) -> bytes:
    data = await cr_svc.query(db, page=1, page_size=MAX_ROWS, **filters)
    wb = Workbook()
    ws = wb.active
    ws.title = "Content Requests"
    headers = ["Key", "Summary", "Status", "Assignee", "Reporter", "Priority",
               "Type", "Created", "Updated", "Due", "Resolved"]
    _header(ws, headers, [12, 60, 18, 22, 22, 12, 18, 12, 12, 12, 12])
    _body(ws, [
        [r["issue_key"], r["summary"], r["status"], r["assignee"], r["reporter"] or "",
         r["priority"], r["issue_type"] or "",
         *(v.date().isoformat() if v else "" for v in (r["created_at"], r["updated_at"])),
         r["due_date"].isoformat() if r["due_date"] else "",
         r["resolved_at"].date().isoformat() if r["resolved_at"] else ""]
        for r in data["items"]
    ], wrap_col=2)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"
    return _save(wb)


# ── summary of the numbers behind the dashboard ───────────────────────────────


async def analytics_xlsx(db: AsyncSession, scope) -> bytes:
    """One sheet per breakdown, so the KPI cards can be checked against rows."""
    from services import analytics as an

    wb = Workbook()
    wb.remove(wb.active)

    async def sheet(title: str, headers: list[str], rows: list[list], widths=None):
        ws = wb.create_sheet(title[:31])
        _header(ws, headers, widths or [22] * len(headers))
        _body(ws, rows)

    s = await an.summary(db, scope)
    await sheet("Summary", ["Metric", "Value"],
                [[k.replace("_", " ").title(), v] for k, v in s.items() if not isinstance(v, dict)],
                [28, 16])
    await sheet("By member",
                ["Member", "Tasks", "Items", "Effort (min)",
                 *[x.replace("_", " ").title() for x in STATUSES], "Completion"],
                [[r["member"], r["tasks"], r["volume"], r["effort_minutes"],
                  *[r[x] for x in STATUSES], r["completion_rate"]]
                 for r in await an.by_member(db, scope)])
    await sheet("By task type",
                ["Task type", "Tasks", "Items", "Effort (min)",
                 *[x.replace("_", " ").title() for x in STATUSES]],
                [[r["task_type"], r["tasks"], r["volume"], r["effort_minutes"],
                  *[r[x] for x in STATUSES]]
                 for r in await an.by_task_type(db, scope)], [32, 10, 10, 12, 10, 12, 10, 10])
    await sheet("Plan adherence",
                ["Member", "Planned", "Reported", "Closed", "No update",
                 "Report rate", "Close rate"],
                [[r["member"], r["planned"], r["reported"], r["closed"], r["no_update"],
                  r["report_rate"], r["close_rate"]]
                 for r in await an.plan_adherence(db, scope)])
    await sheet("By customer", ["Customer", "Tasks", "Items", "Effort (min)", "Outstanding"],
                [[r["customer"], r["tasks"], r["volume"], r["effort_minutes"], r["outstanding"]]
                 for r in await an.by_customer(db, scope, limit=100)], [32, 10, 10, 12, 14])
    return _save(wb)
