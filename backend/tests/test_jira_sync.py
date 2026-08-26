"""The Jira sync's decisions, without touching Jira.

Every case here was a real defect: silent effort drift, tickets stranded on the
wrong person after a reassignment, and a full 1,200-issue re-read on every run.
"""

from datetime import UTC, datetime

import httpx
import pytest

from scripts import backfill_jira as bf


def test_time_in_status_decodes_jiras_format():
    """Verified against TCE-9216: 51m + 27m against 79m actual elapsed."""
    names = {"10000": "TO DO", "10044": "In Progress", "10148": "Done"}
    got = bf._time_in_status(
        "10000_*:*_1_*:*_3079866_*|*_10044_*:*_1_*:*_1654946_*|*_10148_*:*_1_*:*_0",
        names,
    )
    assert got == {"TO DO": 3079866, "In Progress": 1654946, "Done": 0}
    assert round(sum(got.values()) / 60000) == 79


def test_time_in_status_keeps_statuses_it_cannot_name():
    """A status renamed in Jira must read as odd, not vanish into a smaller total."""
    got = bf._time_in_status("99999_*:*_1_*:*_600000", {})
    assert got == {"status:99999": 600000}


@pytest.mark.parametrize(
    "raw", [None, "", "garbage", "10000_*:*_1", "10000_*:*_1_*:*_x"]
)
def test_time_in_status_survives_junk(raw):
    assert bf._time_in_status(raw, {}) in (None, {})


def test_naive_converts_to_utc():
    """Jira sends +0530; the columns are naive. Comparing the two unconverted
    put a resolution before its own creation."""
    aware = datetime.fromisoformat("2026-08-07T11:13:50.000+05:30")
    assert bf._naive(aware) == datetime(2026, 8, 7, 5, 43, 50)
    assert bf._naive(None) is None


def _payload(**fields) -> dict:
    base = {
        "summary": "x",
        "created": "2026-08-07T09:54:42.000+0000",
        "resolutiondate": "2026-08-07T11:13:50.000+0000",
        "issuetype": {"name": "Content Requests"},
        "duedate": None,
        "customfield_10526": 60.0,
        "resolution": {"name": "Done"},
        "priority": {"name": "P2"},
        "customfield_10530": {"value": "Met"},
        "customfield_10013": "10000_*:*_1_*:*_3079866",
    }
    return base | fields


class _Item:
    pass


def test_apply_writes_every_jira_owned_field():
    item = _Item()
    bf._apply(item, _payload(), "closed", "Done", {"10000": "TO DO"})

    assert item.effort_minutes == 60 and item.effort_suspect is False
    assert item.resolved_at == datetime(2026, 8, 7, 11, 13, 50)
    assert item.external_created_at == datetime(2026, 8, 7, 9, 54, 42)
    assert item.resolution == "Done" and item.priority == "P2"
    assert item.sla_met is True
    assert item.time_in_status == {"TO DO": 3079866}


def test_apply_flags_implausible_effort_without_discarding_it():
    item = _Item()
    bf._apply(item, _payload(customfield_10526=3600.0), "open", "To Do", {})
    assert item.effort_minutes == 3600, "kept — deleting it loses information"
    assert item.effort_suspect is True


def test_apply_records_a_missed_sla_and_an_unevaluated_one():
    missed, absent = _Item(), _Item()
    bf._apply(
        missed, _payload(customfield_10530={"value": "Missed"}), "closed", "Done", {}
    )
    bf._apply(absent, _payload(customfield_10530=None), "closed", "Done", {})
    assert missed.sla_met is False
    assert absent.sla_met is None, "no verdict is not a failed verdict"


def _mock(seen: list):
    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"issues": [], "isLast": True})

    return httpx.MockTransport(handler)


def _patch(monkeypatch, seen: list) -> None:
    """Bind the real class before patching. `bf.httpx` IS `httpx`, so a lambda
    that calls `httpx.AsyncClient` after the patch calls itself — that recursion
    already cost an afternoon once on the rate-limit test."""
    real = httpx.AsyncClient
    monkeypatch.setattr(
        bf.httpx,
        "AsyncClient",
        lambda **kw: real(**{**kw, "transport": _mock(seen)}),
    )


async def test_fetch_filters_on_updated_when_given_a_watermark(monkeypatch):
    """Filtering on `created` alone made an issue edited yesterday look identical
    to an untouched one, so every run re-read all 1,200 rows and reassignments
    drifted until the next full pass."""
    seen: list = []
    _patch(monkeypatch, seen)
    await bf.fetch(bf.DEFAULT_FROM, datetime(2026, 8, 3, 14, 30, 55))

    jql = next(u.params["jql"] for u in seen if "jql" in u.params)
    assert 'updated >= "2026-08-03 14:30"' in jql, "minute resolution, rounded down"
    assert 'created >= "2026-05-04"' in jql, "the floor still keeps April out"


async def test_fetch_without_a_watermark_reads_the_whole_window(monkeypatch):
    seen: list = []
    _patch(monkeypatch, seen)
    await bf.fetch(bf.DEFAULT_FROM)

    jql = next(u.params["jql"] for u in seen if "jql" in u.params)
    assert "updated" not in jql and 'created >= "2026-05-04"' in jql


def test_status_map_covers_every_state_jira_actually_uses():
    """An unmapped status silently became 'open', which is how closed work stayed
    in the open column."""
    for name in (
        "To Do",
        "In Progress",
        "Done",
        "REVIEW",
        "Blocked",
        "Invalid Request",
    ):
        assert name.strip().lower() in bf.STATUS_MAP, name


def test_utc_is_imported_for_naive_conversion():
    assert bf.UTC is UTC
