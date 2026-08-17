# ContentOps — Django → FastAPI + React migration plan

Scope source: `/home/hackerearth478/contentops_ref/ContentOps` (current Django app).
Backend conventions source: `/home/hackerearth478/HE-ART`.
Design conventions source: `frontend/DESIGN_REFERENCE.md` (+ HE-ART `frontend/src/theme.css`, `App.css`).

**Decisions locked:** Google OAuth only · Jira writes off the request path · unknown Slack member → 422 · Alembic-only schema changes · app runs locally against a **hosted Supabase Postgres** (`DATABASE_URL` on the 6543 transaction pooler, `DIRECT_URL` on the 5432 session pooler for migrations).

---

## 0. What exists today (audit)

**Django app `tracker`** — 1 app, 1451-line `views.py`, 8 migrations, ~4200 lines of Django templates.

| Model | Rows in `backend/db.sqlite3` | Purpose |
|---|---|---|
| `Member` | 9 | Team member, `role` = content \| ae, `slack_user_id`, `is_active` |
| `DailyEntry` | 13 | One plan or update per member per day; `kind`, `status`, `raw_text`, `source`, Jira key/url, `slack_reply_ts` |
| `EntryItem` | 23 | Task rows. Self-FK `plan_item` links an update row → the plan row it reports on |
| `AEDailyUpdate` | 1 | 11 integer counters + required notes, unique per (member, date) |
| `SlackDayThread` | 7 | One Slack parent msg per (date, kind) |
| `auth_user` | 2 | Django users (admin + 1) |

Second, older DB `data/contentops.sqlite` (`members`/`daily_entries`/`entry_items`, 8/4/8 rows) — pre-Django Node prototype. **Dropped, not migrated.**

**Pages:** Dashboard (KPIs + day chart + member/work-type analysis + work-log table), Plan form, Update form (pre-filled from that day's plan), Members list, Member detail, Reports (+CSV), Content Requests (live Jira board), AE Daily (grid + XLSX), Login.

**Integrations:** Jira Cloud v3 (one issue per task, transitions with the TCE workflow's custom-field validators), Slack (parent message per day+kind, thread reply per entry), Slack intake webhook, XLSX/CSV export.

**Data that lives in code, not the DB** (must move — you asked for everything in the DB):
- `TASK_TYPE_CHOICES` — 11 work types, `forms.py:10`
- `QUESTION_TYPE_CHOICES` — 20 question types, `models.py:60`
- `AE_FIELDS` — 10 AE metric labels, `views.py:983` (and an 11th field `setter_enhancements_count` in the model that the view never writes — dead column)
- Jira config — `jira_config.py`, loaded via `exec()` of a `.py` file
- Slack config — `slack_config.py`, same `exec()` pattern
- Content Requests — fetched live from Jira on *every* page load (1 JQL + full board pagination), never stored

---

## 1. Do these before anything else (security)

Both are committed live credentials in the reference repo's git history:

1. **Rotate the Jira API token** — `backend/.env`, `JIRA_API_TOKEN=ATATT3xFfGF0...` (sreejith@hackerearth.com).
2. **Rotate the Slack bot token** — `backend/slack_config.py:3`, `xoxb-2308587708-...`, committed in plaintext.
3. New repo starts with `.env` gitignored, `.env.example` only. No `exec()`-loaded config files — everything through `pydantic-settings` (HE-ART `core/config.py`).

---

## 2. Directory structure

```
ContentOps/
├── docker-compose.yml            # postgres + api + web, one-command preview
├── README.md
├── .gitignore
│
├── backend/
│   ├── pyproject.toml            # uv, requires-python >=3.13
│   ├── uv.lock
│   ├── alembic.ini
│   ├── .env.example
│   ├── Dockerfile                # uv sync --frozen --no-dev, uvicorn
│   ├── main.py                   # FastAPI app, lifespan, CORS, routers, SPA mount
│   │
│   ├── core/
│   │   ├── config.py             # Settings(BaseSettings) — all env, no exec()
│   │   ├── database.py           # DatabaseManager, get_session (async psycopg)
│   │   ├── orm.py                # all SQLAlchemy models (§3)
│   │   ├── users.py              # fastapi-users, Google OAuth, cookie auth
│   │   ├── deps.py               # current_user, require_role(...), pagination
│   │   ├── scheduler.py          # APScheduler: Jira CR sync, Slack digests
│   │   └── logging.py            # structlog config
│   │
│   ├── api/
│   │   ├── auth_routes.py
│   │   ├── members_routes.py
│   │   ├── entries_routes.py
│   │   ├── ae_routes.py
│   │   ├── analytics_routes.py
│   │   ├── content_requests_routes.py
│   │   ├── intake_routes.py      # Slack webhook (token auth, no cookie)
│   │   ├── export_routes.py
│   │   └── meta_routes.py        # lookups, health, sync status
│   │
│   ├── schemas/                  # Pydantic request/response models
│   │   ├── common.py  members.py  entries.py  ae.py  analytics.py  content_requests.py
│   │
│   ├── services/                 # all query + business logic; routes stay thin
│   │   ├── entries.py            # plan/update creation, status cascade
│   │   ├── analytics.py          # every aggregate in §6
│   │   ├── ae.py
│   │   ├── content_requests.py
│   │   └── export.py             # openpyxl workbooks, CSV
│   │
│   ├── integrations/
│   │   ├── jira.py               # httpx async port of jira_client.py
│   │   └── slack.py              # httpx async port of slack_notify.py
│   │
│   ├── migrations/               # alembic
│   │   ├── env.py                # target_metadata = core.orm.Base.metadata
│   │   └── versions/
│   │
│   ├── scripts/
│   │   ├── import_sqlite.py      # one-shot Django-sqlite → Postgres
│   │   └── seed_lookups.py       # task/question types, AE metric defs
│   │
│   └── tests/
│       ├── conftest.py           # async client + test DB
│       ├── test_entries.py  test_analytics.py  test_intake.py  test_jira.py
│
└── frontend/
    ├── package.json  vite.config.ts  tsconfig.json  Dockerfile  nginx.conf
    ├── index.html
    ├── DESIGN_REFERENCE.md       # already present
    └── src/
        ├── main.tsx  App.tsx  api.ts  types.ts  format.ts
        ├── theme.css  App.css    # copied from HE-ART, palette swapped only
        ├── routes/
        │   ├── Overview.tsx  WorkLog.tsx  Analytics.tsx
        │   ├── PlanForm.tsx   UpdateForm.tsx
        │   ├── Members.tsx    MemberDetail.tsx
        │   ├── AEDaily.tsx    ContentRequests.tsx  Admin.tsx  Login.tsx
        ├── components/         # StatTile, SummaryCard, BarList, SectionHeading,
        │                       # TabNav, VolumeTrendChart, DataTable, StatusPill,
        │                       # PeriodPicker, FilterBar, Skeleton, ErrorBanner …
        └── hooks/
            ├── useAuth.ts  useTheme.ts  usePeriod.ts
            ├── useEntries.ts  useAnalytics.ts  useMembers.ts  useLookups.ts
```

**Why this shape:** HE-ART puts `core/`, `api/`, `dashboard/` flat at repo root. Here everything Python moves under `backend/` because the repo also holds the SPA, and the existing ContentOps tree already splits `backend/` + `frontend/`. `services/` replaces HE-ART's `dashboard/` package — same role (all query logic, routes are thin passthroughs), clearer name.

---

## 3. Database schema (Postgres, SQLAlchemy 2.0 + Alembic)

### 3.1 Auth & identity

**`user`** — fastapi-users `SQLAlchemyBaseUserTable[str]`, verbatim from HE-ART `core/orm.py:167`.
`user_id` (PK, uuid text), `email` (unique), `hashed_password`, `is_active`, `is_superuser`, `is_verified`, `name`, `created_at`, `updated_at`.

**`oauth_account`** — fastapi-users `SQLAlchemyBaseOAuthAccountTable[str]`, FK `user_id` ON DELETE CASCADE.

> Replaces Django `auth_user`. Google OAuth + cookie session, `ALLOWED_EMAILS` gate — same as HE-ART. This kills the current fragile role check `Member.display_name __iexact= request.user.username` (`views.py:1000`).

### 3.2 Core domain

**`members`**
| col | type | notes |
|---|---|---|
| `id` | bigint PK | |
| `display_name` | text NOT NULL UNIQUE | |
| `email` | text UNIQUE NULL | **new** — the real join key to `user` |
| `user_id` | text FK→user NULL, ON DELETE SET NULL | **new** — replaces name-matching |
| `slack_user_id` | text NULL | |
| `role` | text NOT NULL DEFAULT 'content' | CHECK in ('content','ae','manager','admin') |
| `is_active` | bool NOT NULL DEFAULT true | |
| `created_at` / `updated_at` | timestamptz | |

Index: `(is_active, role)`, unique `lower(display_name)` (stops the Slack-intake typo-duplicate problem).

**`task_types`** — *new, was `forms.py:TASK_TYPE_CHOICES`*
`id`, `name` (unique), `slug`, `is_active`, `sort_order`, `created_at`. Seed the 11 existing values.

**`question_types`** — *new, was `models.py:QUESTION_TYPE_CHOICES`*
`id`, `name` (unique), `slug`, `is_active`, `sort_order`. Seed the 20 existing values.

**`daily_entries`**
`id`, `entry_date` date NOT NULL, `kind` text CHECK in ('plan','update'), `status` text CHECK in ('open','in_progress','blocked','closed') DEFAULT 'open', `member_id` FK→members ON DELETE RESTRICT, `raw_text` text NULL, `source` text DEFAULT 'web' CHECK in ('web','slack','api','import'), `jira_issue_key` text NULL, `jira_issue_url` text NULL, `slack_reply_ts` text NULL, `created_by_user_id` FK→user NULL **(new — audit)**, `created_at`, `updated_at`.

Indexes: `(entry_date, kind)`, `(member_id, entry_date)`, `(status)`.
Constraint: **`UNIQUE (member_id, entry_date, kind) WHERE kind = 'plan'`** — one plan per member per day. Today nothing stops two plans, and `_plan_for_member_date()` silently `.first()`s one of them while the dashboard counts both. Updates stay unconstrained (a member may file more than one update a day).

**`entry_items`**
`id`, `entry_id` FK→daily_entries ON DELETE CASCADE, `plan_item_id` FK→entry_items ON DELETE SET NULL (self-ref, updates only), `task_type_id` FK→task_types **(replaces free-text `task_type`)**, `task_type_other` text NULL (for the "Other…" choice), `question_type_id` FK→question_types NULL, `customer` text NULL, `count` int NULL CHECK (count > 0), `notes` text NULL, `due_at` date NULL, `status` text CHECK (same 4), `jira_issue_key`, `jira_issue_url`, `jira_state` text DEFAULT 'none' CHECK in ('none','pending','ok','failed') **(new — Jira writes are now off the request path)**, `jira_error` text NULL, `sort_order` int **(new — the current code relies on `ORDER BY id`)**, `created_at`, `updated_at`.

Indexes: `(entry_id)`, `(plan_item_id)`, `(task_type_id)`, `(status)`, `(due_at)`, `(customer)`, partial `(jira_state) WHERE jira_state IN ('pending','failed')`.

**`entry_item_status_events`** — *new; the single biggest analytics unlock*
`id`, `entry_item_id` FK ON DELETE CASCADE, `from_status`, `to_status`, `changed_at` timestamptz, `changed_by_user_id` FK→user NULL, `source` text ('web','slack','jira','system'), `note` text NULL.
Today status is overwritten in place with no history — cycle time, time-in-status, throughput and reopen-rate are all unanswerable. Write one row on every transition.

**`ae_metric_definitions`** — *new, was `views.py:AE_FIELDS`*
`id`, `key` (unique, e.g. `he_support_replies`), `label`, `sort_order`, `is_active`, `created_at`.

**`ae_daily_updates`**
`id`, `member_id` FK→members RESTRICT, `entry_date` date, `notes` text NOT NULL, `created_by_user_id` FK→user NULL, `created_at`, `updated_at`. UNIQUE `(member_id, entry_date)`, index `(entry_date)`.

**`ae_daily_metrics`** — *new; replaces the 11 hardcoded integer columns*
`id`, `ae_daily_update_id` FK ON DELETE CASCADE, `metric_id` FK→ae_metric_definitions, `value` int NOT NULL DEFAULT 0 CHECK (value >= 0). UNIQUE `(ae_daily_update_id, metric_id)`.
Adding an AE metric becomes a row insert, not a migration + form + view + export edit in four places. (This also drops the dead `setter_enhancements_count` column, which the model declares but no view ever writes.)

### 3.3 Integrations

**`slack_day_threads`** — `id`, `digest_date` date, `kind` text, `channel` text, `parent_ts` text NULL, `created_at`. UNIQUE `(digest_date, kind, channel)` — channel added to the key so switching channels doesn't collide with an old row.

**`content_requests`** — *new; mirrors the Jira board instead of live-fetching per request*
`issue_key` text PK, `summary`, `status`, `status_category`, `assignee`, `reporter`, `priority`, `issue_type`, `labels` text[], `created_at`, `updated_at` (Jira's), `due_date` date NULL, `resolved_at` NULL, `url`, `raw` JSONB, `synced_at` timestamptz.
Indexes: `(status)`, `(assignee)`, `(created_at)`, `(priority)`.
Turns a 2-4 second page load with pagination-over-Jira into an indexed query, and makes historical trend charts possible at all.

**`content_request_snapshots`** — *new, optional but cheap* — `(issue_key, snapshot_date, status, assignee)`, one row per issue per day from the sync job. Gives you real board-state-over-time (aging, status flow) that Jira's API can't retro-answer.

**`sync_cursors`** — `key` PK, `last_synced_at`, `last_status`, `last_error` text NULL. (HE-ART pattern, plus error surface.)

**`integration_settings`** — *new; replaces `jira_config.py` / `slack_config.py`*
`key` text PK, `value` JSONB, `updated_at`, `updated_by_user_id`. Holds Jira project key / issue type / status map / summary prefix, Slack channel, digest post times. **Secrets stay in env, never here.**

**`audit_log`** — *new* — `id`, `user_id`, `action`, `entity_type`, `entity_id`, `payload` JSONB, `created_at`. One insert per mutating request; the current app has zero write trace.

### 3.4 Schema deltas at a glance

| Change | Why |
|---|---|
| `task_types` / `question_types` / `ae_metric_definitions` tables | "all the data in the database" |
| `ae_daily_metrics` long-form | new AE metric = insert, not migration |
| `entry_item_status_events` | cycle time, throughput, reopens |
| `content_requests` + snapshots | Jira analytics + fast page |
| `members.user_id` / `.email` | real auth join, kills name-matching |
| `created_by_user_id` on writes + `audit_log` | accountability |
| unique plan per member/day | fixes silent double-count |
| `entry_items.sort_order` | stable ordering (plan↔update rows are matched positionally today) |

---

## 4. Data migration

1. `alembic upgrade head` on an empty Postgres.
2. `scripts/seed_lookups.py` — insert the 11 task types, 20 question types, 10 AE metric defs, default `integration_settings`.
3. `scripts/import_sqlite.py --db ../contentops_ref/ContentOps/backend/db.sqlite3`
   - `tracker_member` → `members` (9)
   - `auth_user` → skip; invite the 2 users through Google OAuth instead (no password hash migration; Django PBKDF2 ≠ fastapi-users argon2)
   - `tracker_dailyentry` → `daily_entries` (13)
   - `tracker_entryitem` → `entry_items` (23), mapping free-text `task_type`/`question_type` → lookup IDs, unknown values auto-inserted as `task_types` rows flagged `is_active=false`
   - `tracker_aedailyupdate` → `ae_daily_updates` + 10 `ae_daily_metrics` rows each (1 entry)
   - `tracker_slackdaythread` → `slack_day_threads` (7)
   - Backfill one `entry_item_status_events` row per item at `entry.created_at` (`from_status=null`)
   - Idempotent: upsert on natural keys so re-running is safe.
4. Verify: row counts + a spot-check query per table, printed by the script.

Postgres is the only database. No SQLite fallback in dev (the Django app's `dev.sh` runs on SQLite and Postgres in prod — that divergence is how you ship a migration that only breaks in production). Schema changes only ever through Alembic; `Base.metadata.create_all` is never called.

---

## 5. API routes

Conventions: JSON, `snake_case`, cookie auth, `Depends(current_active_user)` everywhere except `/health` and `/api/intake/*`. List endpoints return `{items, total, page, page_size}`. Period params follow HE-ART's regex: `today|yesterday|week|month|quarter|custom:YYYY-MM-DD:YYYY-MM-DD`.

### Auth
| Method | Path | Notes |
|---|---|---|
| GET | `/api/auth/google/login` | first-party CSRF cookie, then redirect |
| GET | `/api/auth/google/callback` | fastapi-users |
| POST | `/api/auth/logout` | |
| GET | `/api/users/me` | returns user + linked `member` + role |
| PATCH | `/api/users/me` | name only |

### Members
| Method | Path | Notes |
|---|---|---|
| GET | `/api/members` | `?role=&is_active=&q=&page=` |
| POST | `/api/members` | admin |
| GET | `/api/members/{id}` | |
| PATCH | `/api/members/{id}` | admin; role/active/email/slack_user_id |
| DELETE | `/api/members/{id}` | soft: sets `is_active=false`; **409 if entries exist and `?hard=true`** |
| GET | `/api/members/{id}/summary` | `?period=` — day/week rollup for MemberDetail |
| GET | `/api/members/{id}/entries` | paginated |

### Entries
| Method | Path | Notes |
|---|---|---|
| GET | `/api/entries` | `?from=&to=&member_id=&kind=&status=&task_type_id=&question_type_id=&customer=&q=&page=&page_size=&sort=` |
| POST | `/api/entries` | body: `{kind, member_id, entry_date, raw_text, items:[…]}`; returns immediately with `jira_state:"pending"` on each item — Jira issue creation and the Slack thread reply run as `BackgroundTasks` after commit |
| GET | `/api/entries/{id}` | with items |
| PATCH | `/api/entries/{id}` | raw_text, status (cascades to items) |
| DELETE | `/api/entries/{id}` | admin only; cascades items, does **not** delete Jira issues (returns their keys so the caller can decide) |
| GET | `/api/entries/plan` | `?member_id=&date=` → the plan + items to prefill the update form; `404` with a typed code if none |
| POST | `/api/entries/updates` | dedicated update submit: `{member_id, entry_date, plan_lines:[{plan_item_id,status,count,notes,due_at}], extra_items:[…]}` |
| GET | `/api/entries/{id}/items` | |
| POST | `/api/entries/{id}/items` | |
| PATCH | `/api/entry-items/{id}` | status/count/notes/due_at → writes status event + Jira transition |
| DELETE | `/api/entry-items/{id}` | |
| GET | `/api/entry-items/{id}/history` | status events |
| POST | `/api/entry-items/{id}/jira` | retry a `failed` Jira write for one item |
| GET | `/api/entries/{id}/jira-state` | `{items:[{id, jira_state, jira_issue_key, jira_error}]}` — the UI polls this until nothing is `pending` |
| GET | `/api/entries/extra-tasks` | `?member_id=&date=` (ports `api_extra_tasks`) |

### AE daily
| Method | Path | Notes |
|---|---|---|
| GET | `/api/ae/metrics` | metric definitions |
| POST/PATCH | `/api/ae/metrics[/{id}]` | admin — add/rename/reorder/deactivate a metric |
| GET | `/api/ae/daily` | `?from=&to=&member_id=` → per-date × per-member grid |
| GET | `/api/ae/daily/{member_id}/{date}` | single |
| PUT | `/api/ae/daily` | upsert `{member_id, entry_date, notes, metrics:{key:value}}`; **409 on stale `updated_at`** (see edge cases) |
| DELETE | `/api/ae/daily/{id}` | admin |
| GET | `/api/ae/summary` | totals + per-metric trend over range |

### Analytics (all `?period=` or `?from=&to=`, plus optional `member_id`, `task_type_id`, `customer`)
| Path | Returns |
|---|---|
| `/api/analytics/summary` | KPI tiles: members active, items, plans, updates, open, closed, blocked, today's plans/updates, completion % |
| `/api/analytics/trend` | plans/updates/items/volume per day\|week\|month |
| `/api/analytics/by-member` | items, plans, updates, status split, volume, completion rate |
| `/api/analytics/by-task-type` | items, volume, status split, avg cycle time |
| `/api/analytics/by-question-type` | items, volume |
| `/api/analytics/by-customer` | items, volume, open count, top-N + "other" |
| `/api/analytics/status-distribution` | current status mix |
| `/api/analytics/status-flow` | transitions matrix from `entry_item_status_events` |
| `/api/analytics/cycle-time` | median/p90 open→closed, overall + by member + by task type |
| `/api/analytics/plan-adherence` | planned vs closed-same-day vs carried over vs never-updated, per member |
| `/api/analytics/aging` | open items bucketed 0-2 / 3-7 / 8-14 / 15+ days, with owner |
| `/api/analytics/due-risk` | items past `due_at` and not closed; due today/this week |
| `/api/analytics/workload` | items + volume per member per day (heatmap) |
| `/api/analytics/throughput` | items closed per day/week (from status events) |
| `/api/analytics/ae-metrics` | per-metric totals + trend + per-member split |
| `/api/analytics/content-requests` | Jira board: by status/assignee/priority/type, created-vs-resolved trend, aging, backlog |
| `/api/analytics/open-items` | drill-down table behind the "open" KPI |

### Content Requests (Jira mirror)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/content-requests` | `?status=&assignee=&priority=&type=&from=&to=&q=&page=` |
| GET | `/api/content-requests/filters` | distinct statuses/assignees/priorities for the filter bar |
| POST | `/api/content-requests/sync` | manual re-sync (the scheduler runs it every 15 min) |

### Intake / integrations
| Method | Path | Notes |
|---|---|---|
| POST | `/api/intake/slack` | header `X-Intake-Token`, constant-time compare; same payload contract as today |
| POST | `/api/integrations/slack/digest` | `{kind, date, dry_run}` — replaces `manage.py post_slack_daily` |
| GET | `/api/integrations/jira/health` | config + auth check, no writes |
| GET/PUT | `/api/integrations/settings` | admin — `integration_settings` rows |

### Exports
`GET /api/exports/worklog.xlsx`, `/worklog.csv`, `/ae-daily.xlsx`, `/content-requests.xlsx` — all take the same filters as their list endpoint.

### Meta
`GET /api/meta/task-types`, `/question-types`, `/statuses`, `/sync-status`, `/health`.
`POST/PATCH/DELETE /api/meta/task-types[/{id}]` — admin CRUD (same for question types).

---

## 6. Analytics you don't have today

Everything under §5 Analytics beyond `summary` / `by-member` / `by-task-type` is new. The ones that matter most:

1. **Cycle time & throughput** — needs `entry_item_status_events`. Median and p90 time open→closed, closed-per-week, per member and per task type.
2. **Plan adherence** — of N tasks planned, how many got an update, how many closed same day, how many carried into the next day. This is the actual point of a plan/update tracker and it's currently unmeasurable.
3. **Aging / carryover** — open items by age bucket, oldest-first, with owner and due date.
4. **Due-date risk** — `due_at` is captured and then never used for anything. Overdue + due-soon lists.
5. **Customer load** — `customer` is free text on every item and never aggregated.
6. **Content Requests trend** — created vs resolved per week, backlog growth, aging by assignee. Impossible today because nothing is stored.
7. **AE metric trends** — currently only a totals column; add per-metric time series and per-member comparison.
8. **Workload heatmap** — member × day, item count and volume.
9. **Status-flow matrix** — how often blocked→closed vs blocked→open (rework signal).
10. **Data quality panel** (HE-ART pattern) — items with no task type, no count, no notes; members with no entry today; plans with no update.

All aggregation in `services/analytics.py` as SQL (`GROUP BY`, window functions, `date_trunc`, `generate_series` for gap-free date axes) — **not** the current pattern of pulling 500 rows into Python and counting in loops (`views.py:191-298`), which silently truncates and produces wrong totals on any range wider than a couple of weeks.

---

## 7. Frontend

**Stack:** Vite + React 18 + TypeScript, `react-router-dom` (the app has real pages and forms, unlike HE-ART's single-page tab switch), `recharts`, `@fontsource-variable/inter` + `jetbrains-mono`. No UI kit, no state library — `useState` + fetch hooks, exactly as HE-ART does.

**Design:** copy `theme.css` and `App.css` from HE-ART verbatim, then change **only** `--accent-*`, `--ord-*`, and the two `--plane`/`--surface` pairs, per `DESIGN_REFERENCE.md` §"To reuse with different colors". Keep: dual dark-mode wiring, fixed status colors, `color-mix` derivation, two-tier shadows, the 10.5–22px type band, uppercase micro-labels, pill-shaped interactive elements, `prefers-reduced-motion` gating, skeleton shimmer, sticky-column tables.

**Routes**

| Path | Page | Notes |
|---|---|---|
| `/login` | Login | Google button only |
| `/` | Overview | KPI tiles, trend chart, member + work-type breakdown, open-items drill-down |
| `/work-log` | WorkLog | the big filterable table, server-paginated, sticky first column, XLSX/CSV buttons |
| `/analytics` | Analytics | sub-tabs: Throughput · Adherence · Aging · Customers · Quality |
| `/plans/new` | PlanForm | dynamic task rows, task/question type from `/api/meta/*` |
| `/updates/new` | UpdateForm | prefilled from `/api/entries/plan`, plan-lines + extra-work sections |
| `/members` | Members | list with entry counts |
| `/members/:id` | MemberDetail | day + week view, task breakdown, personal trend |
| `/ae/daily` | AEDaily | metric grid, submit form, totals, XLSX |
| `/content-requests` | ContentRequests | filters, stats cards, paginated table, trend chart |
| `/admin` | Admin | task/question types, AE metrics, members, integration settings, sync status |

**Shared components:** `StatTile`, `SummaryCard`, `SectionHeading`, `TabNav`, `BarList`, `VolumeTrendChart`, `DataTable` (sticky column + sort + skeleton), `StatusPill`, `PeriodPicker`, `FilterBar`, `Skeleton`, `ErrorBanner`, `Toast`, `ConfirmDialog`, `EmptyState`.

**Hooks:** `useAuth`, `useTheme` (both lifted from HE-ART), `usePeriod` (syncs period ↔ URL query so views are linkable), `useEntries`, `useAnalytics`, `useMembers`, `useLookups`.

**Non-negotiables:** every fetch has a loading skeleton, an error state, and an empty state — the current Django dashboard has none of the three.

---

## 8. Edge cases

### Entries & plan/update linkage
1. **Update with no plan** for that member+date → `404 {code: "no_plan"}`; UI offers "log as extra work" instead of erroring out. (Django handles this at `views.py:376`; keep the behaviour, make it a typed code not a flash message.)
2. **Plan mutated between form load and submit** — send the plan's `updated_at` as an optimistic-lock token; `409 {code: "plan_stale"}` and re-render. (Django's positional `_plan_line_rows` matching is fragile — it pairs formset row *i* to plan item *i*.)
3. **Plan items belonging to a different member/date** posted in `plan_lines` → 422; validate every `plan_item_id` against the resolved plan server-side.
4. **Duplicate plan** for member+date → prevented by the partial unique index; API returns `409 {code:"plan_exists", entry_id}` so the UI can redirect to edit.
5. **Multiple updates in a day** → allowed. Analytics must count *distinct entries*, not rows, everywhere.
6. **Extra tasks are always `closed`** and cannot transition (`views.py:615`). Enforce in the service, return `422 {code:"extra_task_immutable"}`, and grey the control in the UI.
7. **Entry with zero items** — currently renders a phantom row built from `raw_text`. Keep it representable but tag it `is_empty` so KPIs can exclude it from item counts.
8. **`count`** must be `> 0` or null — DB CHECK; the Django form says `min_value=1` but the model allows 0.
9. **Deleting a member with entries** → FK RESTRICT; API returns 409 and suggests deactivation.
10. **Deleting an entry that has Jira issues** → don't delete the issues; return the keys and let the caller act.
11. **`due_at` in the past** on create → allow with a warning flag, don't block (backdated logging is real).
12. **Status cascade**: setting entry status rewrites all its items (`views.py:637`). Keep it, but write a status event per item and make it explicit in the API (`?cascade=true`, default true).
13. **Update row status must also update the linked plan row** and vice versa (`views.py:621-627`). One service function, both directions, one transaction.

### Dates & timezone
14. `TIME_ZONE='Asia/Kolkata'` with `USE_TZ=True`. "Today" must be IST-local, not UTC — a 23:00 IST submission is 17:30 UTC *the same day*, but a 06:00 IST one is the *previous* UTC day. Compute `today` as `(now AT TIME ZONE 'Asia/Kolkata')::date` in SQL, and store `entry_date` as a plain `date`.
15. `from > to` → 422.
16. Range wider than 1 year on a non-paginated analytics endpoint → cap and return `truncated: true` (never silently, unlike today's `qs[:500]`).
17. Weekend/holiday gaps — trend endpoints must return zero-filled dates (`generate_series`), not skip them.
18. Week starts Monday (`_monday()` today) — keep, make it a config value.

### Jira
19. **Not configured** → every Jira call no-ops with `{ok:false, reason:"not_configured"}`; the entry still saves. Never let an integration failure roll back a user's work — wrap Jira/Slack calls *after* the DB commit.
20. **Transition unavailable** — the TCE workflow hides "Done" until "In Progress" (`jira_client.py:311`). Keep the step-through logic, and log every attempted transition to `audit_log`.
21. **Done-transition validators** require Task Type / Question type / Test count / Effort Logged custom fields (`_fetch_done_fields`). Port as-is including the `10244` fallback, but move those custom-field IDs into `integration_settings` instead of hardcoding.
22. **Jira 401/403/429** — retry with backoff on 429/5xx, never on 4xx; surface as a non-blocking warning on the response.
23. **Jira timeout** — 20s today, synchronous, on the request path. Issue creation runs in `BackgroundTasks` **after the DB commit**; the item carries `jira_state='pending'` and the UI polls `/api/entries/{id}/jira-state`.
24. **Partial batch failure** — plan with 5 tasks, 3 issues created then a failure: the 3 land as `ok`, the 2 as `failed` with `jira_error` set, and each retries independently via `POST /api/entry-items/{id}/jira`. No all-or-nothing.
24b. **Background task dies with the process** — a server restart mid-write leaves items stuck `pending`. The scheduler sweeps `jira_state='pending' AND updated_at < now() - 5 min` every 5 minutes and retries. This is the one thing `BackgroundTasks` gives up versus a real queue; the sweeper is ~15 lines and covers it at this volume.
25. **Issue deleted in Jira** → transition 404. Clear `jira_issue_key` and flag the item rather than erroring forever.

### Slack
26. **Token missing / `channel_not_found`** → log + skip, never 500.
27. **Double-post race** — two entries saved concurrently both see `parent_ts IS NULL` and each post a parent. Guard with `INSERT … ON CONFLICT DO NOTHING` on `slack_day_threads` + `SELECT … FOR UPDATE` before posting (today's `IntegrityError` catch at `slack_notify.py:160` handles the row but not the duplicate message).
28. **`slack_reply_ts` already set** → skip (idempotent replay), already correct.
29. **Slack rate limit (429)** → respect `Retry-After`; digest job retries, request-path posts give up quietly.
30. **Message > 40k chars** on a big day → truncate the parent summary, keep replies per entry.

### Intake webhook
31. **Missing/invalid token** → 401, `secrets.compare_digest` (today's `!=` is timing-attackable, `views.py:96`).
32. **Unknown member name** — today `get_or_create` silently creates a member on every typo (`views.py:114`), so "shivendra" / "Shivendr" / "Shivendra " each become a new member and split every per-member metric. Change: match on `lower(trim(display_name))` against the unique index; **no match → 422 `{code:"unknown_member", name}`**, nothing created. Never auto-create from a webhook.
33. **Malformed JSON / wrong `kind` / missing items** → 400 with field detail.
34. **Replay** — same payload twice creates two entries. Add an optional `idempotency_key` on the payload, unique-indexed.
35. **Rate limit** the intake endpoint (per token, e.g. 60/min).

### AE daily
36. **Concurrent submit for the same member+date** — today `get_or_create` + overwrite silently clobbers whoever saved first. Use `updated_at` optimistic locking → 409.
37. **Notes required** (model has `blank=False`) — enforce in schema, min length 1 after strip.
38. **Negative metric values** → DB CHECK ≥ 0 (today's view coerces with `max(0, int(...))`, silently swallowing bad input).
39. **Non-AE member posting AE updates** → 403.
40. **Metric deactivated after rows exist** → historical `ae_daily_metrics` rows stay; the grid shows the metric only for dates where a value exists.

### Auth & access
41. **Google account not on `ALLOWED_EMAILS`** → redirect to `FRONTEND_URL?authError=not_allowed` (HE-ART pattern), don't dump JSON.
42. **User with no linked `member`** — can view, cannot submit. Return `member: null` from `/api/users/me`; UI disables submit affordances.
42b. **No Google account** — with OAuth-only there is no password fallback, so a member without a Workspace account cannot sign in at all. Two of the 9 members currently have entries but no `email` on record; collect those before cutover. Their historical data is unaffected — a `members` row needs no `user_id`.
43. **AE-only pages** — gate on `member.role in ('ae','admin')` server-side (every route), not just by hiding nav links.
44. **Session expiry mid-form** → 401 → UI keeps the form state and shows a re-auth prompt rather than losing the entry.
45. **Cookie flags**: `secure` + `samesite=none` in production, `lax` in dev (HE-ART `core/users.py:118`).

### Exports & data
46. **CSV/XLSX formula injection** — `notes` and `customer` are free text and land in exported cells; prefix any value starting with `= + - @ \t \r` with `'`. The current exports don't, and this is a real remote-code path for whoever opens the file.
47. **Export size** — stream and cap at N rows with an explicit message; a year of data through `openpyxl` in-memory will OOM a small dyno.
48. **Filename** — already uses RFC 5987 `filename*=UTF-8''`; keep.
49. **Unicode / emoji in notes** — Postgres UTF-8 throughout; XLSX must strip illegal control chars (`openpyxl` raises on them).
50. **Very long `notes`** → no DB limit, but truncate in Slack/Jira payloads.

### Query & pagination
51. **Search `q`** joins `entry_items` — needs `DISTINCT` or the entry appears once per matching item (today's `.distinct()` at `views.py:189` is right; the export path repeats it, keep both).
52. **`q` performance** — four `ILIKE '%…%'` columns will table-scan. Add a `pg_trgm` GIN index on `entry_items.notes`, `entry_items.customer`, `daily_entries.raw_text`.
53. **Deep pagination** — offset pagination is fine at this data size; note the ceiling.
54. **Sort by user-supplied column** → allowlist, never string-interpolate into SQL.
55. **N+1** — every entries/analytics query uses `selectinload(DailyEntry.items)`; assert query counts in a test.

---

## 9. Running it (local only)

No hosted deploy for now. `render.yaml`, `build.sh` and the Render env wiring are dropped.

```bash
docker compose up --build
# API      → http://localhost:8000   (docs at /docs)
# SPA      → http://localhost:5173
# Postgres → localhost:5432
```

`docker-compose.yml`, three services:

| service | image / build | notes |
|---|---|---|
| `db` | `postgres:17` | named volume `contentops_pgdata`, port 5432 exposed so you can psql in |
| `api` | `backend/Dockerfile` | `uv sync --frozen` → `alembic upgrade head` → `uvicorn main:app --reload`, source bind-mounted |
| `web` | `node:22` running `npm run dev` | Vite `/api` proxy → `api:8000` (HE-ART `vite.config.ts` pattern), source bind-mounted |

`Makefile`: `make up` · `make down` · `make migrate` · `make revision m="…"` · `make seed` (lookups) · `make import` (SQLite → Postgres) · `make test` · `make fresh` (drop volume, migrate, seed, import).

**Backend without Docker**, if you prefer: `uv sync && uv run alembic upgrade head && uv run uvicorn main:app --reload` against a local Postgres.

**`.env` (dev):**
```
DATABASE_URL=postgresql://contentops:contentops@localhost:5432/contentops
ENVIRONMENT=development
USER_SECRET=<random>
GOOGLE_CLIENT_ID=…
GOOGLE_CLIENT_SECRET=…
FRONTEND_URL=http://localhost:5173
API_BASE_URL=http://localhost:8000
ALLOWED_EMAILS=you@hackerearth.com,…
INTAKE_TOKEN=<random>
JIRA_EMAIL=…            # rotated token
JIRA_API_TOKEN=…
SLACK_BOT_TOKEN=…       # rotated token
```

**Google OAuth for localhost** — in the Google Cloud console, add `http://localhost:8000/api/auth/google/callback` as an authorized redirect URI and `http://localhost:5173` as an authorized JS origin. Google permits `http://localhost` without TLS; no tunnel needed. Cookie flags stay `secure=false, samesite=lax` while `ENVIRONMENT=development`.

**Slack intake in dev** — the webhook needs a public URL. Either point Slack at an `ngrok http 8000` tunnel, or just `curl` the payload from §README against `localhost:8000/api/intake/slack` while testing. Don't repoint the real Slack workflow until there's a hosted instance.

**Not doing yet** (revisit when you deploy): TLS, gunicorn/uvicorn workers, backups, the advisory lock the scheduler needs before more than one instance runs, CDN/static hosting. Single process, single instance — which is exactly what `core/scheduler.py` assumes.

---

## 10. Build order

Each phase ends in something runnable.

**Phase 0 — Security & scaffold** *(0.5d)*
- [ ] Rotate Jira + Slack tokens; confirm the old ones are dead
- [ ] `backend/`: `uv init`, `pyproject.toml`, `.env.example`, `.gitignore`
- [ ] `core/config.py`, `core/database.py`, `core/logging.py`
- [ ] `main.py` with `/api/health` + lifespan
- [ ] `docker-compose.yml` with Postgres → **`docker compose up` serves `/api/health`**

**Phase 1 — Schema & data** *(1.5d)*
- [ ] `core/orm.py`: all §3 tables
- [ ] `alembic.ini` + `migrations/env.py` (HE-ART pattern), initial revision
- [ ] `scripts/seed_lookups.py`
- [ ] `scripts/import_sqlite.py` + verification output → **all 53 existing rows in Postgres**

**Phase 2 — Auth** *(1d)*
- [ ] `core/users.py` (fastapi-users, Google OAuth, cookie, `ALLOWED_EMAILS`)
- [ ] `api/auth_routes.py`, `core/deps.py` (`require_role`)
- [ ] `members.user_id` linking on first login by email → **Google login works, `/api/users/me` returns user + member + role**

**Phase 3 — Core CRUD** *(2.5d)*
- [ ] `schemas/`, `services/entries.py`
- [ ] Members, Entries, EntryItems routes (§5)
- [ ] Status-event writing + status cascade
- [ ] `tests/test_entries.py` covering edge cases 1–13 → **plan and update round-trip via the API**

**Phase 4 — Analytics** *(2.5d)*
- [ ] `services/analytics.py`: all §5 analytics endpoints, SQL aggregates
- [ ] `tests/test_analytics.py` with a fixture dataset, asserting exact numbers → **every §6 metric queryable**

**Phase 5 — Integrations** *(2d)*
- [ ] `integrations/jira.py` (async httpx port; keep the step-through + done-fields logic)
- [ ] `integrations/slack.py` (async port + the parent-race lock)
- [ ] `api/intake_routes.py` (constant-time token, idempotency key, rate limit)
- [ ] `core/scheduler.py`: Content Requests sync (15 min), daily snapshot, plan/update digest at the configured times
- [ ] `content_requests` sync + `/api/content-requests` → **Jira board queryable from Postgres**

**Phase 6 — Exports** *(1d)*
- [ ] `services/export.py`: work-log XLSX/CSV, AE XLSX (port the merged date-header layout), content-requests XLSX
- [ ] Formula-injection escaping + row cap → **byte-comparable to today's exports, plus safe**

**Phase 7 — Frontend shell** *(1.5d)*
- [ ] Vite + TS + router scaffold, `theme.css`/`App.css` copied and repalletted
- [ ] `api.ts`, `types.ts` (generate from OpenAPI or hand-write, matching HE-ART's shape)
- [ ] `useAuth`, `useTheme`, `usePeriod`; Header, TabNav, SectionHeading, StatTile, Skeleton, ErrorBanner
- [ ] Login + protected-route wrapper → **sign in, land on an empty shell**

**Phase 8 — Frontend pages** *(4d)*
- [ ] Overview, WorkLog (DataTable + filters + export)
- [ ] PlanForm, UpdateForm (the two hardest — dynamic rows, plan prefill, optimistic-lock 409 handling)
- [ ] Members, MemberDetail
- [ ] AEDaily, ContentRequests
- [ ] Analytics with sub-tabs
- [ ] Admin → **full feature parity with the Django app**

**Phase 9 — Package & document** *(0.5d)*
- [ ] `docker-compose.yml` (db + api + web), `Makefile`, `README.md` with the run steps
- [ ] `make fresh` from an empty machine → migrate → seed → import → sign in → **the whole app up in one command**

**≈17 working days.** Phases 3–6 (backend) and 7–8 (frontend) can overlap once §5's contract is frozen.

Deferred until you decide to host it: production Dockerfile tuning, TLS, worker processes, scheduler advisory lock, backups, cutover from the Django app.

---

## 11. Decisions

| # | Decision | Consequence |
|---|---|---|
| 1 | **Google OAuth only** — no password path | fastapi-users + `httpx-oauth`, `ALLOWED_EMAILS` gate. Collect Workspace emails for all 9 members before cutover (edge case 42b) |
| 2 | **Jira writes off the request path** | `jira_state` column, `BackgroundTasks` after commit, per-item retry, 5-min stuck-`pending` sweeper (edge cases 23, 24, 24b) |
| 3 | **Unknown Slack member → 422** | case-insensitive match first; nothing auto-created (edge case 32) |
| 4 | **Postgres + Alembic only** | legacy `data/contentops.sqlite` dropped; no SQLite dev fallback; no `create_all` |
| 5 | **Local only for now** | Render config removed; one process, one instance — which is what the in-process scheduler requires anyway |

Still open, but neither blocks Phase 0–4:

- **Week start** — Monday, as today (`_monday()`). Configurable value, defaulted, change it if the team reports on Sun–Sat.
- **`content_request_snapshots`** — daily board-state rows. Cheap and unlocks real aging/status-flow history, but only pays off after a few weeks of collection. Say the word and it goes in Phase 5; otherwise it's a later Alembic revision.

---

## Notes on the deliberate simplifications

- No Celery/Redis. FastAPI `BackgroundTasks` + APScheduler covers Jira writes and the sync jobs at this volume; the stuck-`pending` sweeper (edge case 24b) buys back the one thing a broker would give you. Add the broker when jobs need durable retries across restarts or the sweeper stops being enough.
- No GraphQL, no repository layer, no CQRS. Routes → services → SQLAlchemy, same as HE-ART.
- No UI component library. `theme.css` + `App.css` from HE-ART already carry the design system.
- Offset pagination, not cursor. Correct until the tables are ~100× larger.
- `services/analytics.py` is one module until it passes ~600 lines; split by domain then, not now.
