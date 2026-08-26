"""Cross-check every aggregate against every other one.

    uv run python -m scripts.audit_totals

`reconcile_jira` proves our rows match Jira. This proves the dashboard's own
numbers agree with each other: that the per-member breakdown sums to the
headline, that areas and pipelines partition the work rather than dropping or
double-counting it, that a member's own profile matches their row in the team
table, and that nobody with data is missing from a view.

Written after two people appeared on zero tickets in the UI while holding 71 and
39 tickets in the database — the totals were right, the window was six days in
the future. Nothing compared the two.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

from sqlalchemy import func, select

from core.database import Session
from core.dates import resolve_range
from core.orm import DailyEntry, EntryItem, Member
from services import analytics as an

PERIODS = [None, "today", "yesterday", "week", "month", "quarter"]
FULL = (date(2026, 5, 4), date(2026, 8, 10))

fails: list[str] = []


def check(ok: bool, what: str, detail: str = "") -> None:
    if not ok:
        fails.append(f"{what} {detail}".strip())
    print(
        f"  {'ok  ' if ok else 'FAIL'} {what}{('  ' + detail) if detail and not ok else ''}"
    )


async def audit_window(db, label: str, frm: date, to: date) -> None:
    s = an.Scope(frm=frm, to=to)
    total = await an.summary(db, s)
    members = await an.by_member(db, s)
    areas = await an.by_area(db, s)
    pipes = await an.by_pipeline(db, s)
    types = await an.by_task_type(db, s)

    print(
        f"\n{label}  {frm}..{to}   tasks={total['tasks']} effort={total['effort_minutes']}"
    )

    check(
        sum(m["tasks"] for m in members) == total["tasks"],
        "per-member tasks sum to the headline",
        f"{sum(m['tasks'] for m in members)} != {total['tasks']}",
    )
    check(
        sum(m["effort_minutes"] for m in members) == total["effort_minutes"],
        "per-member effort sums to the headline",
        f"{sum(m['effort_minutes'] for m in members)} != {total['effort_minutes']}",
    )
    # Areas must partition: every ticket in exactly one, none lost, none twice.
    check(
        sum(a["tasks"] for a in areas) == total["tasks"],
        "areas partition the work",
        f"{sum(a['tasks'] for a in areas)} != {total['tasks']}",
    )
    check(
        sum(a["effort_minutes"] for a in areas) == total["effort_minutes"],
        "area effort partitions the work",
        f"{sum(a['effort_minutes'] for a in areas)} != {total['effort_minutes']}",
    )
    check(
        sum(p["tasks"] for p in pipes) == total["tasks"],
        "pipelines partition the work",
        f"{sum(p['tasks'] for p in pipes)} != {total['tasks']}",
    )
    check(
        sum(t["tasks"] for t in types) == total["tasks"],
        "task types partition the work",
        f"{sum(t['tasks'] for t in types)} != {total['tasks']}",
    )
    # Jira owns the issue-type vocabulary, so an unknown type is slugged rather
    # than dropped. What matters is that it still reads as words, not that it
    # was known in advance.
    unlabelled = [a["area"] for a in areas if not a["label"] or "_" in a["label"]]
    check(not unlabelled, "every area renders a readable label", str(unlabelled))

    statuses = sum(total[k] for k in ("open", "in_progress", "blocked", "closed"))
    check(
        statuses == total["tasks"],
        "statuses partition the work",
        f"{statuses} != {total['tasks']}",
    )

    # A window that ends in the future is always wrong: no data can exist there.
    check(to <= date(2026, 8, 10), "window does not run into the future", str(to))


async def audit_people(db) -> None:
    """Everyone holding data must appear in the views that are supposed to
    list them, and their own profile must agree with the team table."""
    frm, to = FULL
    s = an.Scope(frm=frm, to=to)
    members = {m["member"]: m for m in await an.by_member(db, s)}

    async with Session() as _:
        rows = (
            await db.execute(
                select(
                    Member.id,
                    Member.display_name,
                    Member.is_active,
                    func.count(EntryItem.id),
                    func.coalesce(func.sum(EntryItem.effort_minutes), 0),
                )
                .join(DailyEntry, DailyEntry.member_id == Member.id)
                .join(EntryItem, EntryItem.entry_id == DailyEntry.id)
                .where(DailyEntry.entry_date.between(frm, to))
                .group_by(Member.id, Member.display_name, Member.is_active)
                .order_by(func.count(EntryItem.id).desc())
            )
        ).all()

    print(f"\nper-person, {frm}..{to}")
    print(
        f"  {'member':<18}{'db items':>9}{'view':>7}{'db min':>9}{'view min':>9}  active"
    )
    for mid, name, active, n, mins in rows:
        row = members.get(name)
        seen = row["tasks"] if row else None
        seen_min = row["effort_minutes"] if row else None
        # The view excludes update-mirror rows, so items >= tasks by design;
        # effort must match exactly, since it accrues on the plan row.
        bad = row is None or seen_min != int(mins)
        print(
            f"  {name:<18}{n:>9}{str(seen):>7}{int(mins):>9}{str(seen_min):>9}"
            f"  {'y' if active else 'n'}{'   <-- MISMATCH' if bad else ''}"
        )
        if bad:
            fails.append(f"{name}: db={n}/{int(mins)}min view={seen}/{seen_min}min")

        # Their own profile must agree with their row in the team table.
        if row is not None:
            mine = an.Scope(frm=frm, to=to, member_id=mid)
            own = await an.summary(db, mine)
            if (
                own["tasks"] != row["tasks"]
                or own["effort_minutes"] != row["effort_minutes"]
            ):
                fails.append(
                    f"{name}: profile {own['tasks']}/{own['effort_minutes']} "
                    f"!= team row {row['tasks']}/{row['effort_minutes']}"
                )

    print(
        "\n  profile totals match the team table for every member"
        if not any("profile" in f for f in fails)
        else "\n  PROFILE MISMATCH"
    )


async def audit_scoping(db) -> None:
    """A member scoped to themselves must see exactly their own work — not
    less (a broken filter) and not more (a leak)."""
    frm, to = FULL
    print(f"\nscoping, {frm}..{to}")
    for row in (await an.by_member(db, an.Scope(frm=frm, to=to)))[:5]:
        scoped = await an.summary(
            db, an.Scope(frm=frm, to=to, member_id=row["member_id"])
        )
        ok = (
            scoped["tasks"] == row["tasks"]
            and scoped["effort_minutes"] == row["effort_minutes"]
        )
        check(
            ok,
            f"{row['member']} sees their own {row['tasks']} tasks",
            f"scoped={scoped['tasks']}/{scoped['effort_minutes']}",
        )


async def main() -> int:
    async with Session() as db:
        for period in PERIODS:
            frm, to = resolve_range(period, None, None)
            await audit_window(db, f"period={period}", frm, to)
        await audit_window(db, "full range", *FULL)
        await audit_people(db)
        await audit_scoping(db)

    print("\n" + ("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILURES:"))
    for f in fails:
        print("  -", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
