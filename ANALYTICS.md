# Analytics catalogue

Everything the data can answer, split by person and by team.

**Legend** — ✅ built · 🔨 build after backfill · ⚠️ partial, data-limited · ❌ not possible

Backfill window: **2026-05-04 → today**. 1,004 issues, 928 with effort, 2,085 h.

---

## Part 1 — Per person

> "What has Shivendra been working on?"

### Volume and time

| # | Answers | Source | |
|---|---|---|---|
| 1 | Tasks worked | `entry_items` | ✅ |
| 2 | Items produced (questions, docs) | `count` | ✅ |
| 3 | **Hours logged** | `effort_minutes` | ✅ built, 🔨 populated by backfill |
| 4 | Average effort per task | effort ÷ tasks | 🔨 |
| 5 | Average effort per work type — is review costlier than creation for him? | effort ÷ task_type | 🔨 |
| 6 | Share of team — his % of the team's tasks and hours | member ÷ total | 🔨 |

### Where the time goes

| # | Answers | Source | |
|---|---|---|---|
| 7 | **Pipeline split — Content Tasks vs Content Requests**, count and hours | new `pipeline` | 🔨 |
| 8 | **Work areas** — the 14 task types, count + hours + % of his time | `task_types` | ✅ shape, 🔨 hours |
| 9 | Question types he builds — Programming, SQL, Full Stack… | `question_types` | ✅ |
| 10 | **Meeting load** — internal + external meetings as % of his hours | task_type + effort | 🔨 |
| 11 | **Customers served** | `customer` | ⚠️ **Requests only** — set on 211/214 Requests, 1/790 Tasks |
| 12 | Hours per customer | customer + effort | ⚠️ same limit |

### Delivery and quality

| # | Answers | Source | |
|---|---|---|---|
| 13 | Status mix — open / in progress / blocked / done | `status` | ✅ |
| 14 | Completion rate | closed ÷ tasks | ✅ |
| 15 | Plan adherence — planned → reported → closed, and never-updated | plan/mirror rows | ✅ |
| 16 | **Cycle time** median and p90, open → done | status events | ✅ (app data), 🔨 history via changelog |
| 17 | **Effort vs elapsed** — hours worked ÷ days open = how much was *waiting* | effort + events | 🔨 |
| 18 | Rework — his blocked → open transitions | status flow | ✅ |
| 19 | Aging — his open work by age bucket | `entry_date` | ✅ |
| 20 | Overdue and due-soon | `due_at` | ✅ |

### Rhythm

| # | Answers | Source | |
|---|---|---|---|
| 21 | Trend over time, day/week/month bucketed | `trend` + member_id | ✅ |
| 22 | Throughput — tasks closed per week | status events | ✅ |
| 23 | Consistency — days logged vs working days in range | distinct entry_date | 🔨 |
| 24 | Busiest week, quietest week | trend max/min | 🔨 |
| 25 | Every task, drillable, with notes and Jira link | `entry_items` | ✅ |

---

## Part 2 — Team

> "How is the team doing, and where does the work go?"

### Headline

| # | Answers | Source | |
|---|---|---|---|
| 26 | Tasks, items, **hours**, people active | `summary` | ✅ |
| 27 | Completion rate | `summary` | ✅ |
| 28 | Plans and updates filed | `summary` | ✅ |
| 29 | **Total capacity picture** — hours logged vs working hours available | effort + headcount | 🔨 |

### Distribution

| # | Answers | Source | |
|---|---|---|---|
| 30 | **Pipeline mix** — how much of the team is on Requests vs Tasks | `pipeline` | 🔨 |
| 31 | **Where the team's time goes** — hours by work type | task_type + effort | 🔨 |
| 32 | Question type mix | `question_types` | ✅ |
| 33 | **Customer load** — tasks and hours per customer | `customer` | ⚠️ Requests only |
| 34 | Customer concentration — % of Request work in the top 5 accounts | customer | ⚠️ |
| 35 | Member comparison — every person side by side | `by_member` | ✅ |
| 36 | **Workload heatmap** — member × week, tasks / items / hours | `workload` | ✅ |
| 37 | Concentration — is 60% of work on 2 people? | by_member | 🔨 |

### Flow and health

| # | Answers | Source | |
|---|---|---|---|
| 38 | Throughput per week | status events | ✅ |
| 39 | Cycle time overall, by member, by work type | events | ✅ |
| 40 | Status transition matrix — blocked → open is rework | `status_flow` | ✅ |
| 41 | Aging buckets — 0-2 / 3-7 / 8-14 / 15+ days | `aging` | ✅ |
| 42 | Due-date risk — overdue, due today, due this week | `due_risk` | ✅ |
| 43 | Plan adherence league table | `plan_adherence` | ✅ |
| 44 | **Stale work** — the 113 Content Tasks still TO DO | `external_status` | 🔨 |
| 45 | Open items drill-down | `open_items` | ✅ |

### Trust the numbers

| # | Answers | Source | |
|---|---|---|---|
| 46 | Missing effort / notes / customer / question type | `data_quality` | ✅ |
| 47 | Plans nobody ever reported against | `data_quality` | ✅ |
| 48 | Tasks on retired work types | `data_quality` | ✅ |
| 49 | **Suspect effort values** — the 14 outliers above 600 min | `effort_suspect` | 🔨 |
| 50 | Unassigned work | assignee null | 🔨 |

---

## What the data cannot answer

Being explicit so nobody builds a chart on sand.

| Question | Why not |
|---|---|
| **Which customers did someone work for, on Content Tasks?** | `Customer Name` set on **1 of 790** Content Tasks. Only Requests carry it (211/214). |
| **Who requested this work?** | Jira's `reporter` is who *typed the ticket*, not who *wanted the work*. Tickets are raised under Sreejith and reassigned later the same day, so `reporter` is near-constant. **We use `assignee` exclusively.** |
| **Which day were the hours spent?** | Effort Logged is one number per ticket; Jira's per-day worklog is unused (0 entries, `timespent` null). A multi-day ticket attributes all its hours to one date. See the split-work policy above. |
| **Is this person fully utilised?** | 2,085 h over 3 months across ~10 people ≈ 70 h/person/month — roughly 40% of a working month. Effort Logged captures *some* work. Use it to compare, never to conclude someone is idle. |
| **Estimate vs actual** | No estimate field exists. See `EFFORT.md` §6. |
| **Was the work any good?** | Nothing measures quality. Rework (40) is the nearest proxy and it's weak. |
| **Who worked on what together?** | One assignee per issue. No collaboration data. |

## Data caveats worth repeating on screen

1. **"Others" is the largest work type** — 358 of 790 Content Tasks (45%), and all
   214 Requests. Nearly half of everything is uncategorised, so "where does time
   go" is blurrier than the chart will look.
2. **Meetings are 142 tasks** (18% of Content Tasks) before counting External.
3. **14 effort outliers** — top value 3,600 min (60 h on one task). Flagged, not
   averaged.
4. **113 Content Tasks still TO DO** in a 3-month window — either genuinely
   stalled or never closed out.

## Split work across days — the counting policy

**The situation.** Shivendra gets a 2-day Content Request. Rather than log one
lump of effort, he creates a second ticket for day two so each day's work is
recorded separately.

**Why he does it, and why it's not abuse:** Jira's Effort Logged
(`customfield_10526`) is a *single number on the ticket*. Jira's native worklog
— which does carry per-day entries — is **completely unused here**: `timespent`
is null and worklog count is 0 on every issue probed. So splitting the ticket is
the only way anyone can record "2h Monday, 5h Tuesday". It's a workaround for a
missing field, not sloppiness.

**What actually breaks, and what doesn't:**

| | Effect |
|---|---|
| **Total hours per person** | ✅ **Correct.** Minutes are additive — 120 + 300 = 420 either way |
| Ticket count | ⚠️ Inflated: 2 tickets for 1 piece of work |
| Average effort per ticket | ⚠️ Halved, and therefore meaningless as a headline |
| **Pipeline split** | ❌ **Wrong** if the day-2 ticket is filed as a Content Task while the work was a Content Request |
| **Customer hours** | ❌ **Lost** for the same reason — Content Tasks carry no customer |
| Cycle time | ⚠️ The day-2 ticket opens and closes same-day, looking instant |

So the headline number you care about — hours per person — survives this
untouched. The damage is to *counts* and to *attribution*.

**We cannot auto-detect it.** Measured on the 1,004-issue window:

- **0 issues have a parent**; only 12 carry links, all of type `Cloners`
- 44 groups of **exactly identical** summary + assignee, covering 190 tickets

But those duplicates are overwhelmingly **recurring work**, not split work:
`team stand up` ×8, `candidate feedback analysis` ×20, `sync call with shruti`
×8, `test review request | Entri` ×11. Any rule that merged same-summary tickets
would collapse eight separate standups into one. There is no signal in the data
that separates "continued yesterday's task" from "did this again today".

### Policy

1. **Lead with hours, not counts.** Effort is additive and survives splitting.
   Every headline and comparison uses `effort_minutes`.
2. **Call the count "tickets", never "tasks".** It's a count of Jira records, and
   naming it honestly stops it being read as units of work.
3. **Never show average-effort-per-ticket as a headline.** It's a diagnostic,
   shown only next to the caveat.
4. **Do not auto-merge.** Recurring work is indistinguishable from split work.
   Guessing would silently destroy real data.
5. **Fix attribution at the source, not in code.** The one real loss is a
   Content Request continued as a Content Task — customer and pipeline both go
   missing. A process note ("continue Request work as a Request") recovers it;
   no query can.
6. **Make fragmentation visible.** A `tickets per person per day` figure shows
   who splits and how much, so the count is interpreted rather than trusted.

**Optional, if you want true task-level rollup:** `entry_items` already has a
self-referencing `plan_item_id`. A `continues_item_id` on the same pattern would
let someone mark "this is yesterday's task, continued", and the rollup becomes
exact. Only worth it if people will actually set it — see `EFFORT.md` §2 on
fields nobody fills in.

## People

Active in this window, by issue count:

| Jira assignee | Issues | ContentOps member |
|---|---|---|
| Archita Bhanja | 226 | Archita — **name mismatch** |
| Niharika Kanakala | 205 | Niharika K — **mismatch** |
| shruti.jain | 178 | Shruti Jain — **mismatch** |
| shivendra | 175 | Shivendra — case |
| sai.revanth | 67 | Revanth — **mismatch** |
| Arpit Gupta | 63 | **missing — create** |
| Nishu Kumari | 35 | **missing — create** |
| Yogesh Thakur | 30 | Yogesh — mismatch |
| Vishal Reddy | 19 | Vishal — mismatch |
| Santhosh | 3 | Santhosh ✓ |
| Sreejith PV | 1 | missing |
| Unassigned | 2 | — |

aniket.rahane and jiya do **not** appear in this window, so excluding them costs
nothing. `member_aliases` handles every mismatch above.
