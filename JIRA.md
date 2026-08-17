# End-to-end Jira integration — build list

Everything left to make ContentOps and Jira one system: create tickets that carry
real data, pull history back, and analyse both together.

Token verified working 2026-08-05. **No write request has been made to Jira yet.**

---

## Where it stands

| | |
|---|---|
| ✅ Built and mock-tested | `create_issue`, `transition` (with the To Do → In Progress → Done step-through), `push_item`, `push_status`, `sweep_pending`, Content Requests mirror, auth-failure backoff |
| ✅ Verified live | token, identity, 68 projects, all 16 permissions, custom-field IDs, changelog access |
| ❌ Never run live | every write path. Zero issues created or transitioned by this app |
| ⚠️ Known broken | the two items in Block 0 |

---

## Block 0 — Before a single live write

**0.1 — `_done_fields` can zero real Effort Logged.** `integrations/jira.py:150`
carries the issue's current values back through the Done transition:

```python
out[f[name]] = cur.get(f[name]) or 0     # question_count, test_count, effort_logged
```

If the preceding `GET` fails for any reason — 429, timeout, transient 5xx — `cur`
is `{}` and we write **0 over somebody's real Effort Logged**. 928 issues carry
that value; it is the entire effort dataset. Fix: abort the transition if the
read fails, rather than defaulting to zero. *(30m)*

**0.2 — Test against exactly one ticket.** One create, one transition, one
comment, on a throwaway issue. Verify, then delete it. No bulk anything until
that round trip is confirmed by eye. *(30m, needs your go-ahead)*

**0.3 — Scope the credential.** The token is a **site administrator** — 68
projects, `ADMINISTER`, `DELETE_ISSUES`, `BULK_CHANGE`. The app needs browse,
create, transition, comment on TCE. A bug here can delete issues in projects
unrelated to ContentOps. Recommend a dedicated service account. *(yours)*

---

## Block 1 — Outbound: ContentOps → Jira

**Today a ticket created from ContentOps carries only summary, description,
issue type and due date.** Every field the analytics depend on is missing, so
work created in the app is invisible to the reporting the app then does.

| # | Item | Est |
|---|---|---|
| 1.1 | Send **Task Type** (`customfield_10230`) — needs a name → option-id map, fetched once from createmeta and cached in `integration_settings` | 1h |
| 1.2 | Send **Question type** (`customfield_10235`, multi-select) | 45m |
| 1.3 | Send **Question count** (`10233`) from our `count` | 15m |
| 1.4 | Send **Due At** (`customfield_10521`) — distinct from the native `duedate` we already send | 15m |
| 1.5 | Push **Effort Logged** (`10526`) from our `effort_minutes` on every update, so hours flow both ways | 1h |
| 1.6 | Send **Customer Name** (`10225`) on Content Requests | 30m |
| 1.7 | **Set the assignee** — tickets we create are currently unassigned, so they attribute to nobody. Needs `members.jira_account_id` (new column) | 1h |
| 1.8 | **Pick issue type by pipeline** — Content Tasks vs Content Requests, instead of one hardcoded type | 45m |
| 1.9 | Round-trip test: create from ContentOps → backfill reads it → all fields survive | 1h |

**≈6.5h.** Without this block, anything created in the app comes back from Jira
with no task type, no customer, no assignee — a hole in every chart.

---

## Block 2 — Inbound: Jira → ContentOps

| # | Item | Est |
|---|---|---|
| 2.1 | Migration: `entry_items.pipeline`, `external_status`, `effort_suspect`; `members.jira_account_id`; `DailyEntry.source` gains `'jira'` | 45m |
| 2.2 | `member_aliases` table + seed (`shivendra→Shivendra`, `Niharika Kanakala→Niharika K`, `shruti.jain→Shruti Jain`, `Vishal Reddy→Vishal`, `Yogesh Thakur→Yogesh`, `Archita Bhanja→Archita`, `sai.revanth→Revanth`) | 1h |
| 2.3 | Create members: **Arpit Gupta**, **Nishu Kumari** | 15m |
| 2.4 | Add the 4 missing task types (Assessment enhancement, Delivering KT, Help-center article creation/update, Content analytics) | 15m |
| 2.5 | `scripts/backfill_jira.py` — paginated, idempotent on `jira_issue_key`, `--dry-run`, `--from` | 4h |
| 2.6 | Reconcile report before commit: matched / unmatched assignees / suspect effort / unknown task types | 1h |
| 2.7 | Flag the **14 effort outliers** as `effort_suspect`, exclude from averages, list in Admin | 45m |
| 2.8 | Changelog → `entry_item_status_events`, so history has real cycle time | 2h |
| 2.9 | Nightly incremental via the existing scheduler, using `updated >= last_sync` | 1h |
| 2.10 | Conflict rule: Jira is the source of truth for imported rows; app is source of truth for app-created rows | 30m |

**≈11.5h.** Loads 1,004 issues / 2,085 hours from 2026-05-04.

---

## Block 3 — Analytics on the combined data

| # | Item | Est |
|---|---|---|
| 3.1 | `pipeline` filter + `by_pipeline` aggregate across all 16 existing queries | 2h |
| 3.2 | `GET /api/members/{id}/profile` — every dimension in one call | 2h |
| 3.3 | MemberDetail rebuild: pipeline split, hours by work area, customers, share-of-team, meeting load | 5h |
| 3.4 | Team view: pipeline mix, hours by work type, customer load and concentration | 2h |
| 3.5 | **Tickets-per-person-per-day** — makes split-work fragmentation visible rather than hidden | 1h |
| 3.6 | Effort vs elapsed (waiting ratio), needs 2.8 | 1h |
| 3.7 | Stale-work panel — the 113 tickets still TO DO | 45m |
| 3.8 | Exports gain pipeline, customer, effort columns | 1h |
| 3.9 | Rename counts to "tickets" and demote avg-per-ticket, per the split-work policy | 30m |

**≈15h.** Full catalogue in [ANALYTICS.md](ANALYTICS.md).

---

## Block 4 — Operations

| # | Item | Est |
|---|---|---|
| 4.1 | Rate-limit handling — honour `Retry-After` on 429, exponential backoff on 5xx | 1h |
| 4.2 | Audit every Jira write to `audit_log` (table exists, unused) | 45m |
| 4.3 | Surface last-sync, failures and stuck writes in Admin (partly built) | 45m |
| 4.4 | `--dry-run` on every write path, defaulting to on in development | 45m |

**≈3.5h.**

---

## Prerequisite — RBAC

All of [ROLES.md](ROLES.md) Phase 1, **≈2.5 days**. Blocks nothing technically,
but ships before any of this is exposed to the team.

---

## Totals

| Block | | Est |
|---|---|---|
| 0 | Safety before live writes | 1h |
| 1 | Outbound — tickets carry real data | 6.5h |
| 2 | Inbound — backfill + nightly sync | 11.5h |
| 3 | Analytics on combined data | 15h |
| 4 | Operations | 3.5h |
| — | RBAC prerequisite | 20h |

**≈57 hours ≈ 7.5 working days.** Blocks 0–2 alone (a working two-way
integration with history loaded) is **≈19 hours ≈ 2.5 days**.

---

## Decisions still open

1. **RBAC:** members see team aggregates, or only their own data?
2. **Four super-admin emails.**
3. **Approve one live Jira write** for the 0.2 round-trip test.
4. **Outlier threshold** — 600 minutes, flag not drop?
5. **Changelog import** — ~1,000 extra calls for real historical cycle time?
6. **Dedicated Jira service account**, or carry on with the admin token?
