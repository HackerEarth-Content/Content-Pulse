"""Content Health: HE question-library usage, feedback and topic coverage.

Syncs from Redash (see integrations/redash.py) into three tables — one
snapshot row per (period, problem type), one topic row per (period, problem
type, topic/group), one feedback row per period — then serves the Content
Health tab off those tables. A sync replaces the period's rows rather than
accumulating history, same as the plan calls for (latest per period only).

Content Coverage Analysis (the topic/group + ADD/top-up/prune/balanced
verdict) is a direct port of the reference tool's cca.py, in plain Python
rather than pandas — pandas isn't a dependency here and the grouping is a
handful of dict aggregations, not worth adding one for.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from core.database import Session
from core.orm import (
    ContentHealthFeedback,
    ContentHealthSnapshot,
    ContentHealthTopic,
    QuestionType,
    SyncCursor,
)
from integrations import redash
from integrations.redash import PROBLEM_TYPES, RedashDisabled

log = logging.getLogger(__name__)

CURSOR = "redash"
# Matches the reference tool's ThreadPoolExecutor(max_workers=5) — enough to
# beat sequential fetch badly, not so much it queues past Redash's own job
# capacity and times out (see sync()'s comment).
MAX_CONCURRENT_QUERIES = 5

# ---------- Content Coverage Analysis (port of cca.py) ----------

THRESHOLDS = {"AttQ_Under": 30, "AttQ_Tight": 15, "Dead_Prune": 0.6}
NOISE_TAGS = {"approved", "short task", "real world", "growth plan", "trial question"}
STRIP_TAGS = {
    "Full stack": {"fullstack", "full stack", "fs"},
    "DevOps": {"devops"},
    "SQL": {"sql"},
    "Selenium": {"selenium"},
    "Programming": {"programming"},
    "Data Science": {"data science", "datascience"},
    "Machine learning": {"machine learning", "machinelearning", "ml"},
    "Multiple Choice Questions": {"multiple choice questions", "mcq", "mcqs"},
}


def _col(columns: list[dict], *cands: str) -> str | None:
    """Find a column by exact (case-insensitive) name or prefix."""
    lower = {c["name"].lower(): c["name"] for c in columns}
    for c in cands:
        if c.lower() in lower:
            return lower[c.lower()]
    for c in cands:
        for lc, orig in lower.items():
            if lc.startswith(c.lower()):
                return orig
    return None


def _to_float(v: Any) -> float | None:
    try:
        return float(str(v).strip())
    except (ValueError, AttributeError, TypeError):
        return None


def _prefix(title: Any) -> str:
    if not title:
        return "(none)"
    m = re.search(r"\[([^\]]*)\]", str(title))
    return m.group(1).strip() if m else "(none)"


def _topic(tags: Any, strip: set[str]) -> str:
    if not tags:
        return "(untagged)"
    for raw in str(tags).split(","):
        tag = raw.strip()
        if not tag or tag.lower() in NOISE_TAGS or tag.lower() in strip:
            continue
        return tag
    return "(untagged)"


def _action(attq: float, dead: float) -> str:
    if attq >= THRESHOLDS["AttQ_Under"]:
        return "add"
    if attq >= THRESHOLDS["AttQ_Tight"]:
        return "top_up"
    if dead >= THRESHOLDS["Dead_Prune"]:
        return "prune"
    return "balanced"


def compute_cca(result: dict, problem_type: str) -> list[dict]:
    """result = {"columns", "rows"} from query 5156/5549. Returns one dict per
    topic/group, matching content_health_topics' columns."""
    rows = result.get("rows") or []
    if not rows:
        return []
    columns = result.get("columns") or []
    strip = STRIP_TAGS.get(problem_type, {problem_type.lower()})

    c_title = _col(columns, "Title")
    c_diff = _col(columns, "Difficulty_level", "Difficulty")
    c_health = _col(columns, "Health")
    c_tags = _col(columns, "Tags")
    c_att = _col(
        columns,
        "Candidates_attempted_this_question",
        "Candidates_attempted",
        "attempts",
    )

    groups: dict[str, list[dict]] = {}
    # canonical spelling per case/whitespace-normalized group name — the most
    # frequently used original, so "Aggregate functions" and "Aggregate
    # Functions" collapse into one row instead of splitting the count.
    norm_seen: dict[str, dict[str, int]] = {}
    for r in rows:
        attempts = (_to_float(r.get(c_att)) or 0.0) if c_att else 0.0
        health = _to_float(r.get(c_health)) if c_health else None
        prefix = _prefix(r.get(c_title) if c_title else None)
        topic = _topic(r.get(c_tags) if c_tags else None, strip)
        group = prefix if prefix not in ("", "(none)") else topic
        norm = re.sub(r"\s+", " ", group.strip()).lower()
        norm_seen.setdefault(norm, {})
        norm_seen[norm][group] = norm_seen[norm].get(group, 0) + 1
        groups.setdefault(norm, []).append(
            {
                "attempts": attempts,
                "health": health,
                "diff": str(r.get(c_diff) or "").lower(),
            }
        )

    out = []
    for norm, items in groups.items():
        canon = max(norm_seen[norm].items(), key=lambda kv: kv[1])[0]
        n = len(items)
        active = sum(1 for it in items if it["attempts"] > 0)
        attempts = sum(it["attempts"] for it in items)
        dead = (n - active) / n if n else 0.0
        attq = attempts / n if n else 0.0
        healths = [it["health"] for it in items if it["health"] is not None]
        out.append(
            {
                "topic": canon,
                "questions": n,
                "active": active,
                "dead_pct": round(dead * 100, 1),
                "attempts": int(attempts),
                "att_per_q": round(attq, 1),
                "avg_health": round(sum(healths) / len(healths), 1)
                if healths
                else None,
                "difficulty_easy": sum(1 for it in items if it["diff"] == "easy"),
                "difficulty_medium": sum(1 for it in items if it["diff"] == "medium"),
                "difficulty_hard": sum(1 for it in items if it["diff"] == "hard"),
                "action": _action(attq, dead),
            }
        )
    out.sort(key=lambda g: g["attempts"], reverse=True)
    return out


# ---------- KPI / feedback assembly (port of analytics_engine.py) ----------


def _kpi_row_map(result: dict) -> dict[str, Any]:
    return {str(r.get("Name")): r.get("Count") for r in result.get("rows") or []}


def _count_setter_ids(value: Any) -> int:
    if not value:
        return 0
    return len([x for x in str(value).split(",") if x.strip()])


def _sum_attempts(result: dict) -> int | None:
    columns = result.get("columns") or []
    col = next(
        (
            c["name"]
            for c in columns
            if c["name"].lower().startswith("candidates_attempted")
        ),
        None,
    )
    if not col:
        return None
    total = 0.0
    for r in result.get("rows") or []:
        total += _to_float(r.get(col)) or 0.0
    return int(total)


# ---------- sync ----------


async def _question_type_ids(db) -> dict[str, int]:
    """problem_type (lowercased, whitespace-collapsed) -> question_types.id,
    best-effort. A type with no match keeps question_type_id null rather than
    blocking the sync — the raw `problem_type` string is always kept too."""
    rows = (await db.scalars(select(QuestionType))).all()
    return {re.sub(r"\s+", " ", q.name.strip()).lower(): q.id for q in rows}


def _match_qt(name: str, table: dict[str, int]) -> int | None:
    """Case/whitespace-insensitive match — verified against the live
    question_types table that all 8 Redash problem-type labels resolve this
    way (e.g. "Machine learning" / "Machine Learning")."""
    return table.get(re.sub(r"\s+", " ", name.strip()).lower())


async def sync(from_date: date, till_date: date) -> dict:
    """Each Redash query is slow (a live execution, not a cached read) — the
    fetch below runs all of them concurrently rather than accepting minutes
    times ~24 queries sequentially. What isn't accepted is a failure going
    unrecorded: everything from the fetch through the final write is one
    try/except, so *any* failure — network, a malformed Redash response, a
    bug in the aggregation below — still lands in sync_cursors via `_mark`,
    instead of leaving it silently stale.

    No single DB session spans the whole thing, though — a session held open
    (even idle) for the 30-60+ minutes the fetch below can take got the
    connection dropped mid-write by Supabase's transaction pooler in testing
    ("server closed the connection unexpectedly"), losing a fully-fetched
    month's data at the very last step. Sessions here are short-lived: one to
    read question_type_ids, a fresh one only once there's something to write.
    """
    try:
        client = redash._client()
    except RedashDisabled as e:
        async with Session() as db:
            await _mark(db, "disabled", str(e))
        return {"ok": False, "reason": str(e)}

    frm, till = from_date.isoformat(), till_date.isoformat()

    try:
        async with Session() as db:
            qt_ids = await _question_type_ids(db)

        # All ~24 queries (8 KPI + up to 8 attempt + 1 feedback + 8 top10)
        # run concurrently rather than one-by-one — each is a slow, live
        # Redash execution (single-query timing during development: ~4-5
        # minutes), so sequential fetch meant a full month could take
        # hours. Capped at MAX_CONCURRENT_QUERIES rather than run fully
        # unbounded: firing all ~24 at once overloads Redash's own limited
        # job-worker pool, so some queries sit queued long enough to blow
        # past run_query's 20-minute timeout (seen in testing — a full
        # month's Query 5145 timed out under full concurrency). This
        # restores the reference tool's own design
        # (ThreadPoolExecutor(max_workers=5), analytics_engine.generate)
        # rather than inventing a new one.
        sem = asyncio.Semaphore(MAX_CONCURRENT_QUERIES)

        async def limited(qid: str, enum: dict[str, Any]) -> dict:
            async with sem:
                return await redash.run_query(c, qid, frm, till, enum)

        async with client as c:
            tasks: dict[tuple[str, str], asyncio.Task] = {}
            for t, cfg in PROBLEM_TYPES.items():
                tasks[("kpi", t)] = asyncio.create_task(
                    limited(
                        redash.QUERIES["kpi"]["id"],
                        {"required_problem_type": cfg["qt_5163"]},
                    )
                )
                if cfg["attempt_query"]:
                    tasks[("attempt", t)] = asyncio.create_task(
                        limited(
                            cfg["attempt_query"],
                            {
                                "required_problem_type": cfg["attempt_value"],
                                "required_difficulty_level": "All",
                            },
                        )
                    )
                tasks[("top10", t)] = asyncio.create_task(
                    limited(
                        redash.QUERIES["top10"]["id"],
                        {"Problem Type": cfg["qt_5145"]},
                    )
                )
            tasks[("feedback", "")] = asyncio.create_task(
                limited(redash.QUERIES["feedback"]["id"], {})
            )
            await asyncio.gather(*tasks.values())

        kpi_results = {t: tasks[("kpi", t)].result() for t in PROBLEM_TYPES}
        attempt_results = {
            t: tasks[("attempt", t)].result()
            for t in PROBLEM_TYPES
            if ("attempt", t) in tasks
        }
        top10_results = {t: tasks[("top10", t)].result() for t in PROBLEM_TYPES}
        feedback_result = tasks[("feedback", "")].result()

        snapshot_rows, topic_rows = [], []
        for t in PROBLEM_TYPES:
            m = _kpi_row_map(kpi_results[t])
            setter_ids = m.get("Setter IDs", "")
            r_att = attempt_results.get(t)
            top = top10_results.get(t)
            top_rows, value_label = [], None
            if top and top.get("rows"):
                valcol = next(
                    (c["name"] for c in top["columns"] if c["name"] != "Company"), None
                )
                if valcol:
                    value_label = valcol
                    ranked = sorted(
                        top["rows"],
                        key=lambda r: _to_float(r.get(valcol)) or 0.0,
                        reverse=True,
                    )[:10]
                    top_rows = [
                        {"company": r.get("Company"), "value": _to_float(r.get(valcol))}
                        for r in ranked
                    ]
            qt_id = _match_qt(t, qt_ids)
            snapshot_rows.append(
                {
                    "period_from": from_date,
                    "period_to": till_date,
                    "problem_type": t,
                    "question_type_id": qt_id,
                    "tests_published": m.get("Total Tests Published"),
                    "tests_with_qt": m.get("Tests with given problem type"),
                    "tests_with_library": m.get("Tests with HE library problems"),
                    "library_questions_used": _count_setter_ids(setter_ids),
                    "candidates_attempted": _sum_attempts(r_att)
                    if r_att is not None
                    else None,
                    "top_companies": {"value_label": value_label, "rows": top_rows},
                }
            )
            if r_att is not None:
                for g in compute_cca(r_att, t):
                    topic_rows.append(
                        {
                            "period_from": from_date,
                            "period_to": till_date,
                            "problem_type": t,
                            "question_type_id": qt_id,
                            **g,
                        }
                    )

        ratings = [
            v
            for r in feedback_result.get("rows") or []
            if (v := _to_float(r.get("avg_candidate_rating"))) not in (None, 0.0)
        ]
        feedback_row = {
            "period_from": from_date,
            "period_to": till_date,
            "total_slugs": len(feedback_result.get("rows") or []),
            "slugs_with_rating": len(ratings),
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        }

        # A fresh session, opened only now — the fetch above can take the
        # better part of an hour, and nothing DB-related happens during it.
        async with Session() as db:
            for row in snapshot_rows:
                stmt = insert(ContentHealthSnapshot).values(**row)
                await db.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["period_from", "period_to", "problem_type"],
                        set_={
                            k: v
                            for k, v in row.items()
                            if k not in ("period_from", "period_to", "problem_type")
                        },
                    )
                )
            await db.execute(
                delete(ContentHealthTopic).where(
                    ContentHealthTopic.period_from == from_date,
                    ContentHealthTopic.period_to == till_date,
                )
            )
            if topic_rows:
                await db.execute(insert(ContentHealthTopic), topic_rows)
            await db.execute(
                insert(ContentHealthFeedback)
                .values(**feedback_row)
                .on_conflict_do_update(
                    index_elements=["period_from", "period_to"],
                    set_={
                        k: v
                        for k, v in feedback_row.items()
                        if k not in ("period_from", "period_to")
                    },
                )
            )
            await _mark(db, "ok", None)
            await db.commit()
        return {
            "ok": True,
            "problem_types": len(snapshot_rows),
            "topics": len(topic_rows),
        }
    except Exception as e:
        log.warning("redash sync failed: %s", e)
        async with Session() as db:
            await _mark(db, "error", str(e)[:500])
        return {"ok": False, "reason": str(e)[:200]}


async def _mark(db, status: str, error: str | None) -> None:
    await db.execute(
        insert(SyncCursor)
        .values(
            key=CURSOR, last_synced_at=func.now(), last_status=status, last_error=error
        )
        .on_conflict_do_update(
            index_elements=["key"],
            set_={
                "last_synced_at": func.now(),
                "last_status": status,
                "last_error": error,
            },
        )
    )
    await db.commit()


# ---------- read side ----------

ACTION_LABELS = {
    "add": "Under-supplied — ADD",
    "top_up": "Tight — top up",
    "prune": "Oversupplied — prune",
    "balanced": "Balanced",
}


async def usage_overview(db, frm: date, to: date) -> dict:
    rows = (
        await db.scalars(
            select(ContentHealthSnapshot).where(
                ContentHealthSnapshot.period_from == frm,
                ContentHealthSnapshot.period_to == to,
            )
        )
    ).all()
    feedback = (
        await db.scalars(
            select(ContentHealthFeedback).where(
                ContentHealthFeedback.period_from == frm,
                ContentHealthFeedback.period_to == to,
            )
        )
    ).first()
    return {
        "problem_types": [
            {
                "problem_type": r.problem_type,
                "question_type_id": r.question_type_id,
                "tests_published": r.tests_published,
                "tests_with_qt": r.tests_with_qt,
                "tests_with_library": r.tests_with_library,
                "library_questions_used": r.library_questions_used,
                "candidates_attempted": r.candidates_attempted,
            }
            for r in rows
        ],
        "feedback": (
            {
                "total_slugs": feedback.total_slugs,
                "slugs_with_rating": feedback.slugs_with_rating,
                "avg_rating": feedback.avg_rating,
            }
            if feedback
            else None
        ),
        "synced_at": max((r.synced_at for r in rows), default=None),
    }


async def topic_breakdown(db, problem_type: str, frm: date, to: date) -> dict:
    rows = (
        await db.scalars(
            select(ContentHealthTopic)
            .where(
                ContentHealthTopic.problem_type == problem_type,
                ContentHealthTopic.period_from == frm,
                ContentHealthTopic.period_to == to,
            )
            .order_by(ContentHealthTopic.attempts.desc())
        )
    ).all()
    verdicts = {a: 0 for a in ACTION_LABELS}
    for r in rows:
        verdicts[r.action] = verdicts.get(r.action, 0) + 1
    return {
        "topics": [
            {
                "topic": r.topic,
                "questions": r.questions,
                "active": r.active,
                "dead_pct": r.dead_pct,
                "attempts": r.attempts,
                "att_per_q": r.att_per_q,
                "avg_health": r.avg_health,
                "difficulty": {
                    "easy": r.difficulty_easy,
                    "medium": r.difficulty_medium,
                    "hard": r.difficulty_hard,
                },
                "action": r.action,
                "action_label": ACTION_LABELS[r.action],
            }
            for r in rows
        ],
        "summary": {
            "total_questions": sum(r.questions for r in rows),
            "total_attempts": sum(r.attempts for r in rows),
            "topics": len(rows),
            "dead_questions": sum(r.questions - r.active for r in rows),
        },
        "verdicts": verdicts,
    }


async def top_companies(db, problem_type: str, frm: date, to: date) -> dict:
    row = (
        await db.scalars(
            select(ContentHealthSnapshot).where(
                ContentHealthSnapshot.problem_type == problem_type,
                ContentHealthSnapshot.period_from == frm,
                ContentHealthSnapshot.period_to == to,
            )
        )
    ).first()
    if not row:
        return {"value_label": None, "companies": []}
    top = row.top_companies or {}
    return {"value_label": top.get("value_label"), "companies": top.get("rows") or []}
