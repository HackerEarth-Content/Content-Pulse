"""Regression eval for the MCQ Reviewer: a golden set of deliberately flawed
questions (every failure the team reported) plus known-good ones, scored
against the real pipeline.

    cd backend && .venv/bin/python -m scripts.eval_mcq_reviewer

Needs OPENAI_API_KEY and ANTHROPIC_API_KEY (reads .env). Exits non-zero when
recall on critical flaws drops below MIN_RECALL, or when a known-good question
gets a critical flag. Run it whenever the prompts, models, chunk sizes or
thresholds change — the deterministic subset also runs offline in
tests/test_mcq_reviewer_pipeline.py.
"""

from __future__ import annotations

import asyncio
import sys

from services.mcq_reviewer import ParsedRow, review_mcqs

MIN_RECALL = 0.9

# Tags every golden question uses, so tag noise never masks a real result.
TAXONOMY = {"python", "sql", "data structures", "algorithms", "geography"}

# (stem, options, correct option, tags, expected flag(s) — empty set = good).
# Catching ANY ONE expected check counts as catching the flaw: the pipeline may
# name a defect differently (e.g. a wrong key is reported as factual_accuracy).
GOLDEN: list[tuple[str, list[str], int, list[str], set[str]]] = [
    # wrong key
    (
        "What is the time complexity of accessing an array element by index?",
        ["O(n)", "O(1)", "O(log n)", "O(n^2)"],
        1,
        ["Data Structures"],
        {"factual_accuracy"},
    ),
    (
        "What does the Python expression 2 ** 3 ** 2 evaluate to?",
        ["64", "512", "256", "8"],
        1,
        ["Python"],
        {"factual_accuracy"},
    ),
    (
        "What is the worst-case time complexity of binary search on a sorted array of n items?",
        ["O(n)", "O(log n)", "O(n log n)", "O(1)"],
        1,
        ["Algorithms"],
        {"factual_accuracy"},
    ),
    (
        "In standard SQL, what does the expression NULL = NULL evaluate to?",
        ["TRUE", "FALSE", "UNKNOWN", "It raises an error"],
        1,
        ["SQL"],
        {"factual_accuracy"},
    ),
    (
        "Was the year 1900 a leap year in the Gregorian calendar?",
        [
            "Yes, it is divisible by 4",
            "No, it is divisible by 100 but not by 400",
            "Yes, it is divisible by 400",
            "It depends on the country",
        ],
        1,
        ["Python"],
        {"factual_accuracy"},
    ),
    # two correct / none correct
    (
        "Which of the following numbers is prime?",
        ["9", "11", "13", "15"],
        2,
        ["Algorithms"],
        {"multiple_correct"},
    ),
    (
        "What is the capital city of Australia?",
        ["Sydney", "Melbourne", "Perth", "Brisbane"],
        1,
        ["Geography"],
        {"no_correct_answer"},
    ),
    # structural
    (
        "Which data structure follows last-in first-out ordering?",
        ["Stack", "Queue", "Stack", "Heap"],
        1,
        ["Data Structures"],
        {"structural_validation"},
    ),
    (
        "Which data structure follows first-in first-out ordering?",
        ["Stack", "Queue", "Tree", "Graph"],
        5,
        ["Data Structures"],
        {"structural_validation"},
    ),
    # question / option quality
    (
        "Which of these describes a FIFO data structure?",
        ["Queue", "Banana", "Cloud", "Pineapple"],
        1,
        ["Data Structures"],
        {"distractor_quality"},
    ),
    (
        "A queue processes items in first-in first-out order. What ordering does a queue follow?",
        ["FIFO", "LIFO", "Random", "Priority"],
        1,
        ["Data Structures"],
        {"non_triviality"},
    ),
    (
        "Which statement best describes a stack?",
        [
            "A heap",
            "A queue",
            "A graph",
            "A linear structure where insertions and removals happen only at one end, giving last-in first-out order",
        ],
        4,
        ["Data Structures"],
        {"distractor_parity"},
    ),
    (
        "Refer to the diagram below. Which traversal visits the root node first?",
        ["Pre-order", "In-order", "Post-order", "Level-order"],
        1,
        ["Data Structures"],
        {"image_needed"},
    ),
    (
        "What does this Python code print?\nx = [1, 2, 3]\nprint(x[3])",
        ["3", "2", "1", "None"],
        1,
        ["Python"],
        {"code_bug"},
    ),
    # duplicates (reordered options)
    (
        "Which keyword defines a function in Python?",
        ["def", "func", "lambda", "fn"],
        1,
        ["Python"],
        {"duplicate_question"},
    ),
    (
        "Which keyword defines a function in Python?",
        ["fn", "def", "func", "lambda"],
        2,
        ["Python"],
        {"duplicate_question"},
    ),
    # known good
    (
        "What does len([1, 2, 3]) return in Python?",
        ["2", "3", "4", "It raises an error"],
        2,
        ["Python"],
        set(),
    ),
    (
        "Which SQL clause filters groups after a GROUP BY?",
        ["WHERE", "HAVING", "ORDER BY", "LIMIT"],
        2,
        ["SQL"],
        set(),
    ),
    (
        "Which data structure is the best fit for implementing an undo history?",
        ["Stack", "Queue", "Hash table", "Binary heap"],
        1,
        ["Data Structures"],
        set(),
    ),
]


def golden_rows() -> tuple[list[ParsedRow], dict[int, set[str]]]:
    rows, expected = [], {}
    for i, (stem, options, key, tags, expect) in enumerate(GOLDEN):
        n = i + 2  # row 2 = first question, like a real sheet
        rows.append(ParsedRow(n, stem, options, key, "Easy", tags))
        expected[n] = expect
    return rows, expected


def score(result, expected: dict[int, set[str]]) -> tuple[list[str], list[str]]:
    """(missed flaws, false critical flags on good rows)."""
    by_row = {qr.row_number: qr for qr in result.question_reviews}
    missed, false_flags = [], []
    for n, expect in expected.items():
        qr = by_row.get(n)
        flagged = set(qr.checks) if qr else set()
        if expect and not (expect & flagged):
            missed.append(
                f"row {n}: expected {sorted(expect)}, got {sorted(flagged) or 'gtg'}"
            )
        if not expect and qr and qr.verdict == "fail":
            false_flags.append(
                f"row {n}: good question failed with {sorted(qr.checks)}"
            )
    return missed, false_flags


async def main() -> int:
    rows, expected = golden_rows()
    result = await review_mcqs(rows, "", TAXONOMY)
    missed, false_flags = score(result, expected)
    flawed = sum(1 for e in expected.values() if e)
    recall = (flawed - len(missed)) / flawed
    print(f"recall on critical flaws: {flawed - len(missed)}/{flawed} ({recall:.0%})")
    for line in [*missed, *false_flags]:
        print("  -", line)
    ok = recall >= MIN_RECALL and not false_flags
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
