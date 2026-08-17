# Effort logged — plan

Capture hours spent per task, and surface the total per person, per period.

---

## 1. Schema

One nullable column on `entry_items`:

```python
effort_hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
# CHECK (effort_hours IS NULL OR effort_hours >= 0)
```

`Numeric(5,2)` → up to 999.99h at quarter-hour precision. One Alembic revision,
nullable, no backfill — the 23 imported tasks stay `NULL` forever and render as
`—`, not `0`.

**Nullable matters.** "Nobody logged effort" and "this took zero hours" are
different facts. Every average must ignore `NULL`, never coerce it to 0, or a
team that half-fills the field looks twice as fast as it is.

## 2. Where it's captured

| Form | Field | Meaning |
|---|---|---|
| Update → plan line | `effort_hours` | hours spent **since the last update** |
| Update → extra work | `effort_hours` | hours spent on the unplanned task |
| Plan → task | *not captured* | see §6 |
| Status dialog | `effort_hours` | correction, absolute |

Input is `step="0.25"`, so 1.5 and 0.75 are natural to type. Never required —
a mandatory hours field gets guessed at, and guessed numbers are worse than
blank ones.

## 3. The trap: don't sum the mirrors, don't overwrite them either

Analytics counts a **task** as a plan row or a piece of extra work; the update
row mirroring a plan row is excluded, or every total double-counts. So effort
entered on an update line has to land on the **plan row** to be counted at all.

But it must *accumulate*, not overwrite:

> 2h on Monday, 3h on Tuesday against the same planned task = **5h**, not 3h.

`create_update` already writes `count` and `due_at` through to the plan item, so
this follows the same path — except `+=` instead of `=`:

```python
plan_item.effort_hours = (plan_item.effort_hours or 0) + line.effort_hours
mirror.effort_hours = line.effort_hours     # this update's slice, for history
```

`patch_item` stays an absolute set — it edits one row, it isn't a new increment.

Test: two updates on one plan task → member total is 5h, and `tasks` is still 1.

## 4. Where it shows (what you asked for)

| Screen | Addition |
|---|---|
| **Members** table | `Effort (h)` column, per person, for the selected range |
| **Member detail** | `Effort logged` KPI tile · hours column in *What they worked on* · hours in the per-task table |
| **Exports** | `Effort (h)` column in work-log XLSX/CSV · totals in the analytics workbook |
| **Overview** | `Effort logged` tile — team total for the period |

Backend: add `effort` to `summary`, `by_member`, `by_task_type`, `trend`,
`workload`, `by_customer`. All six already share `_from_tasks`, so it's one
`func.sum(EntryItem.effort_hours)` per aggregate.

## 5. Where else it's worth putting

Ranked by value, not effort:

1. **Hours per customer** — `by_customer` already aggregates tasks and items.
   Adding hours answers "what is this account actually costing us", which is the
   one number a content team gets asked for and can never produce.
2. **Effort vs elapsed** — cycle time already measures wall-clock open→done.
   Hours ÷ elapsed = how much of a task's life was *waiting*. A task that took
   6 days and 2 hours is a queueing problem, not a capacity problem. This is the
   most interesting thing the two fields unlock together.
3. **Workload heatmap, third toggle** — Tasks / Items / **Hours** per person per
   week. The toggle is already built; this is one more option.
4. **Hours per work type** — is "Content refixing" eating the month? Sorts the
   `by_task_type` table by something that matters.
5. **Push to Jira** — `integrations/jira.py:45` already maps
   `effort_logged → customfield_10526` and writes `0` into it on every Done
   transition. Sending the real number closes a loop that's already half-wired.
6. **Data quality** — "N tasks closed with no effort logged" belongs next to the
   existing missing-notes / missing-count counters. It's the metric that tells
   you whether to trust the other effort numbers at all.
7. **Slack digest** — "Ada — 4 tasks · 6.5h" in the daily thread.

Not worth it: AE daily (it has its own metric rows, effort would be a 12th),
and plan-adherence (see §6).

## 6. Deliberately not doing: estimate vs actual

The obvious next thought is `estimate_hours` on the plan and `effort_hours` on
the update, then charting estimate-vs-actual. Skipping it:

- it doubles the fields people must fill for a number nobody has asked for yet
- estimate accuracy is a performance-review artefact, and this tool is already
  close to that line
- adding it later is another nullable column and a second migration — cheap

Add when someone actually asks "were we close?".

## 7. Work

| # | | Effort |
|---|---|---|
| 1 | ORM column + Alembic revision | 20m |
| 2 | Schemas: `ItemIn`, `PlanLineIn`, `ItemPatch` | 15m |
| 3 | `create_update` accumulate-onto-plan-row, `patch_item` set | 30m |
| 4 | Six aggregates + exports | 45m |
| 5 | Forms: update lines, extra work, status dialog | 30m |
| 6 | Members column · MemberDetail tile + tables · Overview tile | 45m |
| 7 | Tests: accumulation, NULL-safe averages, mirrors not double-summed | 30m |

**≈3.5 hours.** No dependency on the Jira token or on roles.

## 8. One decision

Hours only, or hours **and** minutes? `Numeric(5,2)` with `step="0.25"` covers
both — 0.25 is 15 minutes — and avoids a second field. Assuming that unless you
say otherwise.
