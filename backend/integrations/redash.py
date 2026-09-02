"""Redash API client — async port of the reference tool's redash_client.py.

Runs a query fresh (max_age=0), polls the job to completion, returns rows.
Only reachable over VPN in practice, so every caller here expects this to
occasionally fail and treats that as a skip, not an outage (see
services/content_health.py and core/scheduler.py).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from core.config import settings

log = logging.getLogger(__name__)

# Query catalog + per-type parameter enums, verbatim from the reference tool
# (queries_config.py) — categories drive services/content_health.py, not this
# client. Parameter keys are Redash's *names*, without the `p_` URL prefix.
QUERIES = {
    "score_dist_fullstack": {
        "id": "5156",
        "enum": {
            "required_problem_type": "FullStack",
            "required_difficulty_level": "All",
        },
    },
    "score_dist_devops": {
        "id": "5549",
        "enum": {"required_problem_type": "DevOps", "required_difficulty_level": "All"},
    },
    "kpi": {"id": "5163"},
    "top10": {"id": "5145"},
    "feedback": {"id": "5215", "enum": {}},
}

# Canonical problem types -> each query's own enum vocabulary (they differ:
# 5163/5145 use "Full stack"/"Machine learning"; 5156 uses "FullStack"/"Machine
# Learning"). attempt_query/attempt_value = which per-question query (and enum
# value) gives "candidates attempted" for that type — DevOps has its own query.
PROBLEM_TYPES: dict[str, dict[str, Any]] = {
    "Full stack": {
        "qt_5163": "Full stack",
        "qt_5145": "Full stack",
        "attempt_query": "5156",
        "attempt_value": "FullStack",
    },
    "DevOps": {
        "qt_5163": "DevOps",
        "qt_5145": "DevOps",
        "attempt_query": "5549",
        "attempt_value": "DevOps",
    },
    "SQL": {
        "qt_5163": "SQL",
        "qt_5145": "SQL",
        "attempt_query": "5156",
        "attempt_value": "SQL",
    },
    "Selenium": {
        "qt_5163": "Selenium",
        "qt_5145": "Selenium",
        "attempt_query": "5156",
        "attempt_value": "Selenium",
    },
    "Programming": {
        "qt_5163": "Programming",
        "qt_5145": "Programming",
        "attempt_query": "5156",
        "attempt_value": "Programming",
    },
    "Data Science": {
        "qt_5163": "Data Science",
        "qt_5145": "Data Science",
        "attempt_query": "5156",
        "attempt_value": "Data Science",
    },
    "Machine learning": {
        "qt_5163": "Machine learning",
        "qt_5145": "Machine learning",
        "attempt_query": "5156",
        "attempt_value": "Machine Learning",
    },
    "Multiple Choice Questions": {
        "qt_5163": "Multiple Choice Questions",
        "qt_5145": "Multiple Choice Questions",
        "attempt_query": None,
        "attempt_value": None,
    },
}


class RedashDisabled(Exception):
    """No API key configured. Callers treat this as skip, same as JiraDisabled."""


class RedashError(Exception):
    pass


def _client() -> httpx.AsyncClient:
    if not settings.REDASH_API_KEY:
        raise RedashDisabled("REDASH_API_KEY not set")
    return httpx.AsyncClient(
        base_url=settings.REDASH_BASE_URL,
        headers={"Authorization": f"Key {settings.REDASH_API_KEY}"},
        timeout=httpx.Timeout(15.0, read=60.0),
    )


async def _send(c: httpx.AsyncClient, method: str, path: str, **kw) -> httpx.Response:
    """Obey 429's Retry-After, back off on 5xx, never retry a 4xx (that's our
    mistake, not theirs) — and tolerate transient network blips, same as the
    reference tool's job-poll loop was explicit about needing to (Redash is
    only reachable over a sometimes-flaky VPN in practice). A poll loop here
    can run for the better part of an hour, hitting Redash every few seconds —
    over that many requests a single dropped connection is normal, not
    exceptional, and used to kill the entire query outright."""
    delay = 1.0
    last_transport_error: httpx.TransportError | None = None
    for attempt in range(10):
        try:
            r = await c.request(method, path, **kw)
        except httpx.TransportError as e:
            last_transport_error = e
            log.warning(
                "redash %s %s network error (attempt %d): %s",
                method,
                path,
                attempt + 1,
                e,
            )
            await asyncio.sleep(min(delay, 30))
            delay *= 2
            continue
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After") or delay)
            log.warning(
                "redash rate limited, waiting %.1fs (attempt %d)", wait, attempt + 1
            )
            await asyncio.sleep(min(wait, 60))
        elif 500 <= r.status_code < 600:
            log.warning("redash %s %s -> %s, retrying", method, path, r.status_code)
            await asyncio.sleep(min(delay, 30))
            delay *= 2
        else:
            return r
    if last_transport_error is not None:
        raise RedashError(
            f"{method} {path} failed after repeated network errors: {last_transport_error}"
        )
    return r


def build_parameters(
    param_defs: list[dict[str, Any]],
    from_date: str,
    till_date: str,
    enum_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map one date range onto a query's (differently-named) parameters,
    verbatim from queries_config.build_parameters."""
    enum_overrides = enum_overrides or {}
    params: dict[str, Any] = {}
    for p in param_defs:
        name = p["name"]
        ptype = (p.get("type") or "").lower()
        lname = name.lower()
        if name in enum_overrides:
            params[name] = enum_overrides[name]
        elif (
            ptype == "date-range"
            or ("range" in lname and "date" in lname)
            or lname == "date range"
        ):
            params[name] = {"start": from_date, "end": till_date}
        elif ptype == "date" and ("from" in lname or "start" in lname):
            params[name] = from_date
        elif ptype == "date" and ("to" in lname or "till" in lname or "end" in lname):
            params[name] = till_date
        elif ptype == "date":
            params[name] = from_date
        else:
            params[name] = p.get("value")
    return params


async def get_query_definition(c: httpx.AsyncClient, query_id: str) -> dict[str, Any]:
    r = await _send(c, "GET", f"/api/queries/{query_id}")
    r.raise_for_status()
    return r.json()


async def run_query(
    c: httpx.AsyncClient,
    query_id: str,
    from_date: str,
    till_date: str,
    enum: dict[str, Any] | None = None,
    poll_interval: float = 3,
    # A full-month range on the heavier per-question queries (5156/5549) can
    # genuinely run past 20 minutes — seen twice in testing, on two different
    # queries, neither a fluke. Long is accepted here; a stuck job isn't, so
    # this stays a bounded wait rather than none at all.
    max_wait: float = 3600,
) -> dict[str, Any]:
    """Run a query fresh for this date range and return {"columns", "rows"}."""
    defs = (
        (await get_query_definition(c, query_id))
        .get("options", {})
        .get("parameters", [])
    )
    params = build_parameters(defs, from_date, till_date, enum)

    r = await _send(
        c,
        "POST",
        f"/api/queries/{query_id}/results",
        json={"parameters": params, "max_age": 0},
    )
    if r.status_code != 200:
        raise RedashError(
            f"Failed to start query {query_id} ({r.status_code}): {r.text}"
        )
    data = r.json()

    if "query_result" in data:
        result_id = data["query_result"]["id"]
    else:
        job_id = data["job"]["id"]
        waited = 0.0
        while True:
            job = (await _send(c, "GET", f"/api/jobs/{job_id}")).json()["job"]
            status = job["status"]
            if status == 3:  # SUCCESS
                result_id = job["query_result_id"]
                break
            if status == 4:  # FAILURE
                raise RedashError(
                    f"Query {query_id} failed: {job.get('error', 'Unknown error')}"
                )
            if waited >= max_wait:
                raise RedashError(f"Query {query_id} timed out after {max_wait}s")
            await asyncio.sleep(poll_interval)
            waited += poll_interval

    r = await _send(c, "GET", f"/api/queries/{query_id}/results/{result_id}.json")
    r.raise_for_status()
    result = r.json()["query_result"]["data"]
    return {"columns": result.get("columns", []), "rows": result.get("rows", [])}
