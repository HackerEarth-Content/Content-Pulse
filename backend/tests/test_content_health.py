"""Pure-function coverage for the CCA port and the Redash->question_types
name match — the two pieces of services/content_health.py with real logic
(the rest is fetch-and-store)."""

from services.content_health import _match_qt, compute_cca


def _row(title, tags, attempts, difficulty="Easy", health=None):
    return {
        "Title": title,
        "Tags": tags,
        "Candidates_attempted_this_question": attempts,
        "Difficulty_level": difficulty,
        "Health": health,
    }


COLUMNS = [
    {"name": "Title"},
    {"name": "Tags"},
    {"name": "Candidates_attempted_this_question"},
    {"name": "Difficulty_level"},
    {"name": "Health"},
]


def test_compute_cca_verdict_buckets():
    rows = [
        # "Loops" group: 1 question, 40 attempts/question -> ADD (Att/Q >= 30)
        _row("[Loops] find max", "loops, programming", 40),
        # "Recursion": 2 questions, avg 20 attempts -> top up (>=15, <30)
        _row("[Recursion] fib", "recursion, programming", 25),
        _row("[Recursion] factorial", "recursion, programming", 15),
        # "Sorting": 2 questions, both dead -> prune (Att/Q<15, dead%>=0.6)
        _row("[Sorting] bubble", "sorting, programming", 0),
        _row("[Sorting] merge", "sorting, programming", 0),
        # "Strings": 1 question, 5 attempts -> balanced
        _row("[Strings] reverse", "strings, programming", 5),
    ]
    result = {"columns": COLUMNS, "rows": rows}
    groups = {g["topic"]: g for g in compute_cca(result, "Programming")}

    assert groups["Loops"]["action"] == "add"
    assert groups["Recursion"]["action"] == "top_up"
    assert groups["Sorting"]["action"] == "prune"
    assert groups["Sorting"]["dead_pct"] == 100.0
    assert groups["Strings"]["action"] == "balanced"

    # every group sums back to the input — no question silently dropped.
    assert sum(g["questions"] for g in groups.values()) == len(rows)


def test_compute_cca_empty_input():
    assert compute_cca({"columns": COLUMNS, "rows": []}, "Programming") == []


def test_match_qt_is_case_and_whitespace_insensitive():
    table = {"full stack": 1, "machine learning": 2, "multiple choice questions": 3}
    assert _match_qt("Full stack", table) == 1
    assert _match_qt("Machine learning", table) == 2
    assert _match_qt("  Multiple   Choice Questions ", table) == 3
    assert _match_qt("Nonexistent", table) is None
