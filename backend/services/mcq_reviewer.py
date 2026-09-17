"""MCQ Reviewer — the Utils tab's first tool.

A setter uploads a bulk-MCQ workbook in the exact HackerEarth template
format. We validate it (columns present, in the exact order), then hand the
rows to an LLM running utils.prompts.MCQ_REVIEWER_PROMPT: OpenAI first,
Anthropic as a fallback if OpenAI errors or returns something that doesn't
fit the schema. Both calls are traced to LangSmith. The set-level summary
(counts, answer-choice distribution, complexity-mismatch rate) is computed
here in Python from the parsed rows and the model's per-row verdicts, not
trusted from the model's own aggregation — deterministic and can't drift
from what was actually parsed.
"""

from __future__ import annotations

import io
import json
import logging
import os
from dataclasses import dataclass, field

import openpyxl
import xlrd
from anthropic import AsyncAnthropic
from langsmith import traceable
from openai import AsyncOpenAI
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel

from core.config import settings
from core.database import Session
from core.orm import AuditLog, McqReviewJob
from schemas.mcq_review import (
    MCQReviewResult,
    OverallResults,
    QuestionReview,
    SetSummary,
)
from services import taxonomy as taxonomy_service
from services.export import safe
from utils.prompts import MCQ_REVIEWER_PROMPT

log = logging.getLogger(__name__)

if settings.LANGSMITH_API_KEY:
    os.environ.setdefault("LANGSMITH_API_KEY", settings.LANGSMITH_API_KEY)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.LANGSMITH_PROJECT)
    os.environ.setdefault("LANGSMITH_TRACING", "true")

# The exact HackerEarth bulk-upload template header row, in this exact order.
# Reordering, inserting, or dropping a column is a hard rejection — the
# reviewer maps values positionally, not by matching header names, so a
# silently-reordered file would otherwise score the wrong field as the wrong
# check without anyone noticing.
EXPECTED_COLUMNS = (
    "Problem statement",
    "Option 1",
    "Option 2",
    "Option 3 (optional)",
    "Option 4 (optional)",
    "Correct option number (1, 2, 3, 4...etc.)",
    "Correct score",
    "Negative marking (optional)",
    "Difficulty (Easy, Medium, Hard)",
    "Timed restriction per question in seconds (optional)",
    "Skill/topic tags",
    "Partial Scoring Enabled (optional)",
    "Shuffle Options (optional)",
)

# ponytail: single LLM call per job, no chunking — comfortably fits a normal
# bulk-upload set in one context window. If real usage regularly exceeds
# this, add chunking + merge in review_mcqs rather than raising the cap
# indefinitely.
MAX_ROWS = 500
MAX_FILE_BYTES = 10 * 1024 * 1024


class TemplateValidationError(Exception):
    """The uploaded file doesn't match the template — never worth an LLM
    call. Carries the exact reason so the frontend can show it verbatim."""


class ReviewFailedError(Exception):
    """Both OpenAI and Anthropic failed, or neither produced a schema-valid
    response. Carries the last error seen for the audit trail."""


@dataclass
class ParsedRow:
    row_number: int  # 1-based spreadsheet row, header excluded (row 2 = first question)
    problem_statement: str
    options: list[str]
    correct_option: int | None
    difficulty: str
    skill_tags: list[str] = field(default_factory=list)

    @property
    def is_structurally_valid(self) -> bool:
        return (
            bool(self.problem_statement.strip())
            and len(self.options) >= 2
            and self.correct_option is not None
            and 1 <= self.correct_option <= len(self.options)
        )


def _clean(v) -> str:
    return str(v).strip() if v is not None else ""


def _to_int(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _split_tags(v) -> list[str]:
    return [t.strip() for t in _clean(v).split(",") if t.strip()]


def _rows_from_sheet(header: list[str], data_rows: list[tuple]) -> list[ParsedRow]:
    validate_columns(header)
    parsed = []
    for i, r in enumerate(data_rows):
        row_number = i + 2  # header is row 1
        options = [_clean(r[j]) for j in (1, 2, 3, 4) if _clean(r[j])]
        parsed.append(
            ParsedRow(
                row_number=row_number,
                problem_statement=_clean(r[0]),
                options=options,
                correct_option=_to_int(r[5]),
                difficulty=_clean(r[8]),
                skill_tags=_split_tags(r[10]),
            )
        )
    return parsed


def validate_columns(header: list[str]) -> None:
    """Position-by-position match against EXPECTED_COLUMNS. Reordering,
    inserting, or removing a column fails here — before any LLM call."""
    got = [_clean(h) for h in header]
    if len(got) < len(EXPECTED_COLUMNS):
        raise TemplateValidationError(
            f"Expected {len(EXPECTED_COLUMNS)} columns, found {len(got)}."
        )
    for i, expected in enumerate(EXPECTED_COLUMNS):
        actual = got[i] if i < len(got) else "(missing)"
        if actual != expected:
            raise TemplateValidationError(
                f"Column {i + 1} must be {expected!r} in this exact position, "
                f"found {actual!r}. Columns cannot be reordered, renamed, "
                "inserted, or removed."
            )


def _read_raw_rows(content: bytes, filename: str) -> tuple[list, list[tuple]]:
    """Header row + data rows, straight off the sheet with no cleaning —
    shared by parse_workbook (which derives ParsedRow from it) and
    build_reviewed_workbook (which needs every original column verbatim to
    append Pass/Fail/Suggestion onto)."""
    if len(content) > MAX_FILE_BYTES:
        raise TemplateValidationError(
            f"File is larger than the {MAX_FILE_BYTES // (1024 * 1024)}MB limit."
        )

    lower = filename.lower()
    try:
        if lower.endswith(".xlsx"):
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            ws = wb.worksheets[0]
            rows = list(ws.iter_rows(values_only=True))
        elif lower.endswith(".xls"):
            wb = xlrd.open_workbook(file_contents=content)
            ws = wb.sheet_by_index(0)
            rows = [
                tuple(ws.cell_value(r, c) for c in range(ws.ncols))
                for r in range(ws.nrows)
            ]
        else:
            raise TemplateValidationError(
                "Unsupported file type — upload the .xls or .xlsx bulk template."
            )
    except TemplateValidationError:
        raise
    except Exception as e:
        raise TemplateValidationError(f"Could not read the file: {e}")

    if not rows:
        raise TemplateValidationError("The file is empty.")
    header, data_rows = list(rows[0]), rows[1:]
    if not data_rows:
        raise TemplateValidationError("The file has a header row but no questions.")
    if len(data_rows) > MAX_ROWS:
        raise TemplateValidationError(
            f"{len(data_rows)} questions found — the limit is {MAX_ROWS} per upload."
        )
    return header, data_rows


def parse_workbook(content: bytes, filename: str) -> list[ParsedRow]:
    header, data_rows = _read_raw_rows(content, filename)
    return _rows_from_sheet(header, data_rows)


RED_FILL = PatternFill("solid", fgColor="FFC7CE")
RED_FONT = Font(color="9C0006")
BOLD_HEADER = Font(bold=True)


def build_reviewed_workbook(
    content: bytes, filename: str, result: MCQReviewResult
) -> bytes:
    """The original uploaded sheet, unchanged column-for-column, with Pass,
    Fail, and Suggestion appended. A row's verdict comes from whether it has
    a QuestionReview — rows with none passed every check. Fail=Yes rows get
    a red fill on the Fail cell so a reviewer scanning the sheet spots them
    without reading every row."""
    header, data_rows = _read_raw_rows(content, filename)
    failed_by_row = {qr.row_number: qr for qr in result.question_reviews}

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reviewed"

    new_header = [*header, "Pass", "Fail", "Suggestion"]
    for col, label in enumerate(new_header, 1):
        cell = ws.cell(row=1, column=col, value=label)
        cell.font = BOLD_HEADER

    for i, raw_row in enumerate(data_rows):
        row_number = i + 2
        excel_row = i + 2
        for col, value in enumerate(raw_row, 1):
            ws.cell(row=excel_row, column=col, value=safe(value))

        qr = failed_by_row.get(row_number)
        failed = qr is not None
        pass_col = len(header) + 1
        fail_col = len(header) + 2
        suggestion_col = len(header) + 3
        ws.cell(row=excel_row, column=pass_col, value="No" if failed else "Yes")
        fail_cell = ws.cell(
            row=excel_row, column=fail_col, value="Yes" if failed else "No"
        )
        if failed:
            fail_cell.fill = RED_FILL
            fail_cell.font = RED_FONT
        ws.cell(
            row=excel_row,
            column=suggestion_col,
            value=safe(qr.suggestion) if qr else "",
        )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _llm_input(rows: list[ParsedRow]) -> str:
    return json.dumps(
        [
            {
                "row_number": r.row_number,
                "problem_statement": r.problem_statement,
                "options": r.options,
                "correct_option": r.correct_option,
                "difficulty": r.difficulty or None,
                "skill_tags": r.skill_tags,
            }
            for r in rows
        ]
    )


def _filter_valid_reviews(
    rows: list[ParsedRow], question_reviews: list[QuestionReview]
) -> list[QuestionReview]:
    """Drop any review whose row_number isn't one we actually sent. A
    hallucination or a row_number an injected instruction in some cell
    talked the model into fabricating would otherwise corrupt the
    deterministic counts in _build_summary or show a nonexistent row on the
    frontend's flagged-questions list."""
    valid_row_numbers = {r.row_number for r in rows}
    kept = [qr for qr in question_reviews if qr.row_number in valid_row_numbers]
    if len(kept) != len(question_reviews):
        log.warning(
            "mcq_reviewer: dropped %d review(s) for row_numbers not in the uploaded file",
            len(question_reviews) - len(kept),
        )
    return kept


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


class _LLMQuestionReviews(BaseModel):
    """What we actually trust from the model — the per-row verdicts. The
    set_summary it may also send is ignored; ours is computed deterministically
    in _build_summary below."""

    question_reviews: list[QuestionReview] = []


@traceable(name="mcq_reviewer.openai", run_type="llm")
async def _call_openai(system: str, user: str) -> str:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    resp = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return resp.choices[0].message.content or ""


@traceable(name="mcq_reviewer.anthropic", run_type="llm")
async def _call_anthropic(system: str, user: str) -> str:
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = await client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _build_summary(
    rows: list[ParsedRow], question_reviews: list[QuestionReview]
) -> SetSummary:
    failed_by_row = {qr.row_number: qr for qr in question_reviews}
    total = len(rows)
    failed = len(question_reviews)
    passed = total - failed

    structural_failures = sum(
        1 for qr in failed_by_row.values() if "structural_validation" in qr.checks
    )
    clear_defects = sum(
        1
        for qr in failed_by_row.values()
        if any(c.status == "fail" for c in qr.checks.values())
    )
    borderline_failures = failed - clear_defects

    overall = OverallResults(
        total=total,
        passed=passed,
        failed=failed,
        pass_pct=round(100 * passed / total, 2) if total else 0.0,
        fail_pct=round(100 * failed / total, 2) if total else 0.0,
        structural_failures=structural_failures,
        clear_defects=clear_defects,
        borderline_failures=borderline_failures,
        overall_status="clean" if failed == 0 else "issues_found",
    )

    most_frequent: dict[str, dict] = {}
    for qr in failed_by_row.values():
        for check_name in qr.checks:
            most_frequent.setdefault(check_name, {"count": 0})
            most_frequent[check_name]["count"] += 1
    for check_name, info in most_frequent.items():
        info["pct_of_reviewed"] = (
            round(100 * info["count"] / total, 2) if total else 0.0
        )

    # Only structurally valid rows (deterministic, computed from parsed data —
    # not from the model) contribute to the distribution, grouped by option count.
    valid_rows = [r for r in rows if r.is_structurally_valid]
    by_option_count: dict[int, list[ParsedRow]] = {}
    for r in valid_rows:
        by_option_count.setdefault(len(r.options), []).append(r)

    distribution = {}
    for n, group in by_option_count.items():
        expected_pct = round(100 / n, 2)
        counts = {str(i): 0 for i in range(1, n + 1)}
        for r in group:
            counts[str(r.correct_option)] += 1
        observed = {
            k: round(100 * v / len(group), 2) if group else 0.0
            for k, v in counts.items()
        }
        status = (
            "within_tolerance"
            if all(abs(v - expected_pct) <= 5 for v in observed.values())
            else "exceeds_tolerance"
        )
        distribution[f"{n}_option"] = {
            "sample_size": len(group),
            "expected_distribution": {k: expected_pct for k in counts},
            "observed_distribution": observed,
            "tolerance": "5 percentage points",
            "status": status,
        }

    mismatches = sum(
        1
        for qr in failed_by_row.values()
        if "complexity" in qr.checks and qr.checks["complexity"].status != "na"
    )
    structurally_valid_count = len(valid_rows)
    complexity_mismatch = {
        "structurally_valid_rows_assessed": structurally_valid_count,
        "rows_with_mismatch": mismatches,
        "mismatch_pct": (
            round(100 * mismatches / structurally_valid_count, 2)
            if structurally_valid_count
            else 0.0
        ),
    }

    tags_not_provided = sum(
        1
        for qr in failed_by_row.values()
        if qr.checks.get("skill_tags")
        and qr.checks["skill_tags"].tag_status == "tags_not_provided"
    )
    taxonomy_missing = any(
        qr.checks.get("skill_tags")
        and qr.checks["skill_tags"].status == "taxonomy_not_provided"
        for qr in failed_by_row.values()
    )
    skill_tag_gaps = {"rows_missing_tags": tags_not_provided}
    skill_tag_analysis_status = "taxonomy_not_provided" if taxonomy_missing else None

    return SetSummary(
        overall_results=overall,
        most_frequent_issues=most_frequent,
        answer_choice_distribution=distribution,
        complexity_mismatch=complexity_mismatch,
        skill_tag_gaps=skill_tag_gaps,
        skill_tag_analysis_status=skill_tag_analysis_status,
    )


async def review_mcqs(rows: list[ParsedRow], taxonomy_block: str) -> MCQReviewResult:
    """OpenAI first; Anthropic on any failure (network, rate limit, invalid
    JSON, or a response that fails schema validation). Both failing raises
    ReviewFailedError — never a silently partial or fabricated result."""
    system = MCQ_REVIEWER_PROMPT
    if taxonomy_block:
        system += (
            "\n\n---\n\n"
            "## Skill Taxonomy Reference (hackerearth-skill-taxonomy.md)\n\n"
            + taxonomy_block
        )
    user = _llm_input(rows)

    last_error: Exception | None = None
    for provider, call in (("openai", _call_openai), ("anthropic", _call_anthropic)):
        try:
            raw = await call(system, user)
            parsed = _LLMQuestionReviews.model_validate_json(_strip_fences(raw))
            question_reviews = _filter_valid_reviews(rows, parsed.question_reviews)
            log.info(
                "mcq_reviewer: %s served the review (%d rows, %d flagged)",
                provider,
                len(rows),
                len(question_reviews),
            )
            return MCQReviewResult(
                question_reviews=question_reviews,
                set_summary=_build_summary(rows, question_reviews),
            )
        except Exception as e:
            log.warning("mcq_reviewer: %s failed: %s", provider, e)
            last_error = e

    raise ReviewFailedError(
        f"Both OpenAI and Anthropic failed to produce a valid review: {last_error}"
    )


async def run_review_job(job_id: int, content: bytes) -> None:
    """The background task kicked off by POST /api/utils/mcq-reviewer. Opens
    its own DB session — the request's session is gone by the time a
    BackgroundTasks callback runs (same pattern as services.content_issues.sync).
    Every stage transition is persisted on the job row and logged to AuditLog,
    so a failure anywhere still leaves a clear, queryable trail of what was
    uploaded, by whom, and whether it finished."""
    async with Session() as db:
        job = await db.get(McqReviewJob, job_id)
        if job is None:
            return

        async def _stage(status: str, **payload) -> None:
            job.status = status
            await db.commit()
            db.add(
                AuditLog(
                    user_id=job.user_id,
                    action=f"mcq_reviewer.{status}",
                    entity_type="mcq_review_job",
                    entity_id=str(job_id),
                    payload={"filename": job.filename, **payload},
                )
            )
            await db.commit()

        try:
            await _stage("parsing")
            rows = parse_workbook(content, job.filename)
            await _stage("parsed", row_count=len(rows))

            await _stage("reviewing")
            taxonomy_block = await taxonomy_service.taxonomy_prompt_block(db)
            result = await review_mcqs(rows, taxonomy_block)

            job.result = result.model_dump(mode="json")
            await _stage("done", row_count=len(rows))
        except TemplateValidationError as e:
            job.error = str(e)
            await _stage("failed", error=str(e), reason="template_validation")
        except ReviewFailedError as e:
            job.error = str(e)
            await _stage("failed", error=str(e), reason="llm_failure")
        except Exception as e:  # pragma: no cover - unexpected, never leave a job stuck
            log.exception("mcq_reviewer: job %s crashed", job_id)
            job.error = f"Unexpected error: {e}"
            await _stage("failed", error=str(e), reason="unexpected")
