# ContentOps — end-to-end project description

**What it is:** a daily plan/update tracker for HackerEarth's content team, filed against Jira Cloud, with a full analytics layer on top. FastAPI + Postgres (Supabase) backend, React SPA frontend. Currently on branch `feat/member-drilldown`, actively evolving — AE tracking was just removed, RBAC and a Jira backfill (3 months, ~1,000 issues) just landed.

Written as a redesign brief: what exists today, what it displays, and what a frontend redesign needs to account for.

---

## 1. The core workflow

One person, one day, one screen: **`/my-day`** (just replaced the old separate Plan-form/Update-form pair).

- No plan yet for the selected date → **"Start the day"**: add task rows (task type, question type, customer, count, due date, notes), submit → creates a `daily_entries` (kind=plan) row + `entry_items`, fires Jira issue creation and a Slack post in the background.
- Plan exists → **"Day in progress"**: KPI tiles (Planned / Done / Effort so far / To report), each planned item editable inline (status, effort minutes, due date, notes) or via a `StatusDialog` modal (status pill → Open/In progress/Blocked/Done, due date, effort, a comment that posts to Jira), plus an "unplanned work" section for ad-hoc tasks. Submitting only sends changed/new rows.
- Leads (admin/manager) get a member picker to file on someone else's behalf.

This plan→update pair is the atomic unit everything else aggregates: an "update" mirrors its plan row (`plan_item_id` link) so it's never double-counted, and every status change writes a row to `entry_item_status_events` — the append-only log that makes cycle time, throughput, and rework calculable at all.

---

## 2. Site map (current nav)

| Nav label | Route | Purpose |
|---|---|---|
| My day | `/my-day` | plan/report today |
| Overview | `/` | headline numbers for the period |
| All tickets | `/work-log` | every ticket, filterable, exportable |
| People | `/members` | per-person workload table |
| — | `/members/:id` | deep per-person profile |
| Request streams | `/requests` | non-content-task pipelines drill-down |
| Insights | `/analytics` | delivery/timing/customer/quality tabs |
| Settings | `/admin` | admin-only: members, lookups, integrations |
| (off-nav) | `/content-requests` | raw Jira board mirror, not effort-analytics |
| — | `/login` | Google OAuth only |

A global `PeriodPicker` (Today/Week/Month/Quarter + custom range, synced to the URL) sits top-right on every page and drives every query. A persistent `TodayStrip` under the header always shows the signed-in user's own plan/update status plus team completion counts.

---

## 3. What "work" actually is (the data model underneath everything)

- **`daily_entries`** — one plan or one update, per member per day (`kind`, `status`, `source`: web/slack/api/import/jira).
- **`entry_items`** — the actual task rows. Each carries: `task_type_id`, `question_type_id`, `customer` (free text), `count`, `notes`, `due_at`, `status`, `effort_minutes` (nullable — null means "never logged," distinct from 0), `effort_suspect` (flagged outlier from the Jira backfill), `pipeline` (content_task / content_request / hc_request / ht_request / hc_ht_feasibility / technical_writing / creation_and_review), `external_status`/`external_issue_type`/`request_type` (Jira's raw values, kept verbatim), and Jira linkage (`jira_issue_key`, `jira_state`: none/pending/ok/failed, `jira_error`).
- **`entry_item_status_events`** — full transition history, the backbone of every "how long / how often" metric.
- Three months of Jira history (790 Content Tasks + 214 Content Requests, ~2,085 hours) has been backfilled into this same schema via `member_aliases` name-mapping, so imported and live-logged work sit in the identical tables and every aggregate below already spans both.

**Known caveats that should shape the redesign**, not just be footnotes:

- **Customer attribution only exists for Content Requests** (99% coverage) — essentially absent on Content Tasks (0.1%). Any "who did you work for" view needs to visibly scope itself to Requests, not silently show a mostly-empty chart.
- **"Others" is ~45% of Content Tasks** and 100% of Requests' task-type field — nearly half of "where does time go" is uncategorized.
- **Effort is a single number per ticket**, not per-day — a multi-day task is either one ticket (all hours land on one date) or split into two tickets (inflates ticket counts, but hours stay correct). Docs mandate leading with *hours*, never ticket-count, as the headline; calling the count "tickets" not "tasks" is deliberate language.
- **A real bug for the redesign to know about:** `effort_suspect` (outliers >600 min, e.g. one 3,600-min ticket) is stored but **not currently excluded from any aggregate** — every effort sum today includes the outliers, contradicting the documented policy.
- Reporter/assignee: only `assignee` is meaningful (who did the work); Jira's `reporter` is whoever typed the ticket, functionally constant, and unused.

---

## 4. Analytics — page by page, what's actually rendered today

### Overview (`/`)
Narrative summary sentence, then: KPI row (Tasks, Items produced, Completion %, In progress, Blocked, Effort logged, Plans/updates filed) → "Where the effort goes" (donut: Tasks vs Requests&Programs hours + ranked bars of busiest work areas) → "Activity" (bar+line combo chart, tasks vs closed, bucketed by day/week/month) → By-member and By-work-type ranked bars side by side → "Risk & timing" (due-date KPI row + cycle-time KPI row) → "Open work" table (12 rows, links out to Work Log).

### Work Log (`/work-log`)
Item-level table, one row per ticket. Filters: free-text search, member, stream, status, work type, customer. Columns: Member, Date, Stream, Work type, Customer, Items, Effort, Status (clickable → StatusDialog), Due, Jira link/state, Notes. Server-paginated (50/page), Excel/CSV export.

### Insights (`/analytics`) — 4 tabs
- **What shipped**: plan adherence table (Planned/Reported/Closed/Never updated/rates per member), throughput ranked bars, status-transition matrix ("blocked → open" = rework signal), workload heatmap (member × time, metric toggle: Tasks/Items/Effort).
- **How long it took**: cycle-time KPIs (median, p90, tasks measured) + by-member/by-task-type breakdowns; aging buckets (0-2/3-7/8-14/15+ days).
- **Who it was for**: by-customer table, top-2-customer concentration donut, question-type ranked bars.
- **Can we trust it** (data quality): plans never reported, tasks on retired work types, and missing-field rates (notes/count/customer/question type/due date/effort) — each as % of tickets.
- Whole-workbook export button.

### People (`/members`)
Team table (role, email-linked status, tasks/items/effort/open/blocked/completion/never-updated per person) + two ranked-bar panels ("Effort logged" hours, "Tickets" count+completion%).

### Member detail (`/members/:id`)
The richest single view — one composite `profile` API call renders: header + narrative; KPI row (effort, tickets, share-of-team %, completion, customer count); donut of pipeline/stream split + ranked-bars of work areas; customers (Requests only) and question-type ranked bars; a second KPI row (tasks/items/effort/completion/open/blocked/median cycle time); an output-over-time combo chart; a plan-adherence card; a "what they worked on" table by work type with computed totals; and a full drillable task history table.

### Request streams (`/requests`)
Scoped to everything that isn't a plain content task (Content Requests, Assessments, Programs & Technical Writing). Top level: donut of the three streams + clickable ranked-bars of every area. Clicking an area drills into: KPI row (tickets/effort/done%/open/people), who-worked-on-it, request-type breakdown, customer ranked-bars, aging buckets.

### Content Requests board mirror (`/content-requests`, off-nav)
Distinct from the above — this is the raw synced Jira board, not effort analytics: KPI row (issues, open backlog, statuses, assignees, last sync), by-status/by-assignee bar lists, filterable paginated table, manual "Sync from Jira" action.

### Admin (`/admin`)
Member CRUD (email/role/active toggle), task-type/question-type lookup lists (retire, don't delete), integrations panel (sync status per job, Jira health check, retry stuck writes, Slack digest preview/post).

---

## 5. Analytics catalogue — the full underlying API surface

Every screen above is a client for `services/analytics.py`, which exposes (all scoped by period/member/task-type/pipeline/customer): `summary`, `trend` (zero-filled daily), `by_member`, `by_area`, `by_pipeline`, `by_request_type`, `by_task_type`, `by_question_type`, `by_customer`, `status_flow`, `cycle_time` (median/p90 via Postgres percentile_cont, overall + by member + by task type), `plan_adherence`, `aging`, `due_risk`, `throughput` (from the status-event log, not current-state), `workload` (heatmap source), `open_items` (row-level, scoped to viewer unless a lead), `data_quality`. Plus `members/{id}/profile`, which bundles most of these for one person in a single call.

Documented-but-not-yet-built: capacity picture (hours logged vs. available), consistency/busiest-week, concentration (% of work on top N people), unassigned-work, and a stale-by-Jira-status view (`external_status` is stored but nothing aggregates on it directly yet).

---

## 6. Access model

Three tiers on `members.role`: **admin** (named super-admins, full read/write/admin), **manager** (full read/write, no admin), **member** (sees team-wide *aggregates* everywhere, but row-level detail — notes, individual tickets — only for themselves). Google OAuth only, member table doubles as the allowlist. This is implemented in `core/deps.py`, applied per-route (the ROLES.md doc itself flags "a missed endpoint is a data leak" as the main residual risk — 36 of 55 routes are member-attributable).

---

## 7. Current design system (what a redesign is either keeping or replacing)

"Quiet enterprise data dashboard" — dense, restrained, not flashy:

- Design tokens: `--plane`/`--surface` (bg layers), `--ink`/`--ink-2`/`--ink-3` (3-level text), fixed `--status-*` colors (never re-themed), single-hue `--ord-*` ramp for severity/ordinal scales, two radii only (12px cards, pill 999px for anything clickable).
- One sans + one mono (mono reserved for tabular numbers), 10.5–22px type band, hierarchy from weight/letter-spacing not size, uppercase micro-labels.
- `color-mix()`-derived tints everywhere instead of hardcoded shades — the main cohesion trick.
- Chart vocabulary is narrow and deliberate: **Donut** (max 3 categorical slices + folded "Other," always with a clickable legend) for part-of-whole; **RankedBars** (single-hue intensity ramp) for anything with >3 categories; **ComposedChart** (bar+line) for time series; **WorkloadHeatmap** for member×time density. Recharts is the only charting library in use.
- Every async view goes through one `Async<T>` wrapper (loading skeleton / error / empty / data) — no bespoke loading states per page.

This is the concrete starting point for a redesign: the information architecture (7 nav destinations + drilldowns), the ~17 analytics dimensions already computed server-side, and the specific chart/table vocabulary currently rendering them.



