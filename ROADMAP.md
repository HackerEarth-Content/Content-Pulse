# RBAC → Backfill → Granular per-person analytics

Two phases in order: lock down who sees what, then load 3 months of real work
from Jira so the analytics have something to analyse.

All Jira figures below are measured, not estimated — read-only `GET` probes run
2026-08-05. **No write request has been made to Jira.**

---

## What's actually in Jira since 2026-05-04

| | Content Tasks | Content Requests |
|---|---|---|
| Issues | **790** | **214** |
| Effort Logged set | 717 (91%) | 211 (99%) |
| Total effort | 94,814 min ≈ **1,580 h** | 30,285 min ≈ **505 h** |
| Median effort | 80 min | 90 min |
| Date range | 2026-05-04 → 2026-08-05 | 2026-05-04 → 2026-08-05 |
| Done / open | 670 Done, 113 TO DO, 7 WIP | 208 Done, 6 other |
| Task Type | 14 distinct values | all "Others" |
| **Customer** | **1 of 790** | **211 of 214 (99%)** |

**1,004 issues, 928 with effort, ~2,085 hours.** That is the whole backfill.

Full catalogue of what this makes answerable: **[ANALYTICS.md](ANALYTICS.md)**.

### Five things the data says that change the plan

1. **Customer attribution only exists for Content Requests.** `Customer Name` is
   set on 211 of 214 Requests (Entri 25, HCL tech 8, Google 7, Tredence 5 …) and
   on **1 of 790** Content Tasks. "Which customers did Shivendra work for" is
   answerable for Requests and essentially unanswerable for Tasks. Nothing code
   can fix — the field was never filled in.
2. **"Others" is 45% of Content Tasks** (358 of 790) and 100% of Requests, with
   "Internal meeting" next at 142. Nearly half the work is uncategorised, so
   "where does the time go" is blurrier than any chart will look.
3. **2,085 h over 3 months across ~10 people ≈ 70 h/person/month** — about 40%
   of a working month. Effort Logged captures *some* work, not all of it.
   Relative signal, never a timesheet.
4. **14 effort outliers.** Top value 3,600 min — 60 hours on one task. Import
   raw and every average is wrecked.
5. **Reporter is not a usable dimension.** Jira's `reporter` records who *typed
   the ticket*, not who *wanted the work* — Sreejith filed 772 of 777 Requests
   on everyone's behalf. Every bar would read "Sreejith". `assignee` (who did
   it) and `Customer Name` (who it was for) are what carry meaning.

---

## Phase 1 — RBAC

Per `ROLES.md`, with the decision still open there (aggregates vs strict
isolation). Recommendation stands: three tiers, members see team **aggregates**
but only their own **row-level detail**.

| # | Item | Est |
|---|---|---|
| 1.1 | `SUPERADMIN_EMAILS` env (4 addresses), bootstrap on OAuth callback, drop `ALLOWED_EMAILS` | 2h |
| 1.2 | `viewer` dependency returning a forced `scope_member_id` | 2h |
| 1.3 | Apply to entries, AE, row-level analytics, all 5 exports | 4h |
| 1.4 | Derive `member_id` from session on writes; reject someone else's id | 2h |
| 1.5 | Restore role gating on admin routes (`members_routes.py:21` marks the spot) | 1h |
| 1.6 | Frontend: hide Admin nav, unlinked-account state, "filing as" everywhere | 4h |
| 1.7 | **Leak test that walks every route** and asserts a member can't read another's row | 4h |
| 1.8 | Fill in 11 member emails | you |

**≈2.5 days.** 1.7 is not optional — 36 of 55 routes return member-attributable
data, and route-by-route scoping will eventually miss one.

---

## Phase 2 — Backfill

### 2.1 Schema

Three additions to `entry_items`, one migration:

```python
pipeline: Mapped[str]                 # content_task | content_request | internal
jira_issue_key                        # already exists — becomes the dedupe key
external_status: Mapped[str | None]   # Jira's raw status, kept verbatim
```

Plus `DailyEntry.source` gains `'jira'`, and `pipeline` gets an index.

**Why this shape:** imported issues become ordinary `entry_items` under a
synthetic plan entry per (member, date). Every one of the 16 existing aggregates
then works on 3 months of history with **no query changes** — they already
group by member, task type, question type, customer and date. `pipeline` is the
one genuinely new dimension.

The one-plan-per-member-per-day index means one synthetic entry per person per
day holding that day's issues. ~500 entries, ~1,000 items.

### 2.2 Storage

| Table | Rows | Notes |
|---|---|---|
| `entry_items` | ~1,000 | one per Jira issue |
| `daily_entries` | ~500 | one per member per day |
| `entry_item_status_events` | ~2,500 | 2-3 per issue from changelog |
| `content_requests` | 214 | the existing mirror table |

**≈4,200 rows, a few MB.** Supabase free tier is 500 MB. Storage is irrelevant
at this size; the pull is ~11 API calls at 100/page — under a minute.

### 2.3 Mapping

| Jira | ContentOps |
|---|---|
| `assignee.displayName` | `members.display_name` — needs an alias table, see below |
| `created` | `daily_entries.entry_date` |
| `customfield_10526` Effort Logged | `entry_items.effort_minutes` |
| `customfield_10230` Task Type | `task_types` (add ~4 missing values) |
| `customfield_10235` Question type | `question_types` (multi → take first) |
| `customfield_10225` Customer Name | `entry_items.customer` (Requests only) |
| `customfield_10521` Due At | `due_at` |
| status | `status` + `external_status` |
| changelog | `entry_item_status_events` |

**Name mapping needs a decision.** Jira has `shivendra`, `shruti.jain`,
`Niharika Kanakala`, `Vishal Reddy`, `Yogesh Thakur` — ContentOps has
`Shivendra`, `Shruti Jain`, `Niharika K`, `Vishal`, `Yogesh`. Two Jira names have
no member and are wanted: **Arpit Gupta (63)** and **Nishu Kumari (35)** — create
them. aniket.rahane and jiya do not appear in this window at all, so excluding
them costs nothing. Full table in [ANALYTICS.md](ANALYTICS.md#people).

### 2.4 Outliers

Import raw into `effort_minutes`, but **flag rather than trust**: anything above
a threshold you set (600 min = 10 h?) gets `effort_suspect = true`, is excluded
from averages, and is listed in Admin for correction. Deleting the value loses
information; averaging it loses the truth.

### 2.5 Idempotency

`jira_issue_key` is unique per import. Re-running upserts, never duplicates —
same discipline as `scripts/seed.py`. The job can then run nightly to keep
history current instead of being one-shot.

| # | Item | Est |
|---|---|---|
| 2.1 | Migration: `pipeline`, `external_status`, `effort_suspect`, indexes | 30m |
| 2.2 | `member_aliases` table + seed from your confirmed mapping | 1h |
| 2.3 | `scripts/backfill_jira.py` — paginated, idempotent, dry-run flag | 4h |
| 2.4 | Changelog → status events (optional, ~1,000 extra calls) | 2h |
| 2.5 | Reconcile report: matched / unmatched / suspect, printed before commit | 1h |
| 2.6 | Nightly incremental via the existing scheduler | 1h |

**≈1 day** — a quarter of the volume of the 2025 window.

---

## Phase 3 — The per-person view you described

One endpoint, `GET /api/members/{id}/profile?from&to`, returning every dimension
at once, and one redesigned page.

**"What has Shivendra been working on":**

| Panel | Source | Available? |
|---|---|---|
| Pipeline split — Tasks vs Requests | new `pipeline` column | ✅ after backfill |
| Hours logged, by pipeline | `effort_minutes` | ✅ 92% coverage |
| Work areas — Task Type breakdown | `task_types` | ✅ 14 values |
| Question types — what he builds | `question_types` | ✅ |
| **Customers worked for** | `customer` | ⚠️ **Requests only** (1% on Tasks) |
| Share of team — his % of tasks/hours | existing aggregates | ✅ |
| Trend over time, bucketed | existing `trend` | ✅ already built |
| Cycle time vs effort — waiting vs working | events + effort | ✅ after 2.4 |
| Every task, drillable | existing entries table | ✅ already built |

| # | Item | Est |
|---|---|---|
| 3.1 | `by_pipeline` aggregate + `pipeline` filter on all existing ones | 2h |
| 3.2 | `/members/{id}/profile` composite endpoint | 2h |
| 3.3 | Rebuild MemberDetail around it: pipeline donut, hours by area, customer table, share-of-team | 5h |
| 3.4 | Same dimensions team-wide on Analytics | 2h |
| 3.5 | Add pipeline + customer columns to exports | 1h |

**≈1.5 days.**

---

## Hit list

| # | | Blocked on |
|---|---|---|
| 1 | RBAC 1.1 – 1.7 | your call: aggregates vs own-data-only, + 4 admin emails |
| 2 | Member emails (11) | you |
| 3 | Backfill schema + alias table | name mapping confirmation |
| 4 | `backfill_jira.py`, dry-run first | outlier threshold |
| 5 | Verify counts, then commit the load | — |
| 6 | Changelog → status events | — |
| 7 | Pipeline aggregates + profile endpoint | 3 |
| 8 | MemberDetail rebuild | 7 |
| 9 | Nightly incremental sync | 4 |
| 10 | Exports gain pipeline + customer | 7 |

**≈5.5 days total.**

## Decisions needed before I start

1. **RBAC:** members see team aggregates (recommended) or only themselves?
2. **The four super-admin emails.**
3. **Name mapping** — confirm `shivendra → Shivendra`, `Niharika Kanakala →
   Niharika K`, `Vishal Reddy → Vishal`, `Yogesh Thakur → Yogesh`,
   `shruti.jain → Shruti Jain`, `Archita Bhanja → Archita`,
   `sai.revanth → Revanth`. Creating **Arpit Gupta** and **Nishu Kumari** as new
   members, per your call. Also: Sreejith PV has 1 issue — create or skip?
4. **Outlier threshold** — 600 minutes? And flag-not-drop, as proposed?
5. **Backfill Content Tasks only, or both pipelines?** Both is the same work and
   Requests is where the customer data lives, so I'd do both.
6. **Changelog import** — ~1,000 extra calls, a few minutes, and the only way to
   get real cycle time for history. Worth it?
