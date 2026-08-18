# ContentPulse (ContentOps)

Daily plan/update tracker and Jira/Slack dashboard for the content team.
FastAPI + Postgres (Supabase) + React. Full history and scope decisions:
[PLAN.md](PLAN.md), [ANALYTICS.md](ANALYTICS.md), [JIRA.md](JIRA.md).

## Run it

Postgres is hosted on Supabase; only the API and SPA run locally.

```bash
cp backend/.env.example backend/.env    # fill DATABASE_URL, USER_SECRET, Google keys
make migrate && make seed
make up
```

- API — http://localhost:8000 (`/docs` for the interactive schema)
- SPA — http://localhost:5173

| command | does |
|---|---|
| `make up` / `make down` | start / stop the Docker stack |
| `make migrate` | `alembic upgrade head` |
| `make revision m="…"` | autogenerate a migration from `core/orm.py` |
| `make seed` | lookups + legacy Django SQLite import (idempotent) |
| `make test` | pytest (161 tests) |

Backend without Docker:

```bash
cd backend && uv sync && uv run uvicorn main:app --reload
```

Frontend without Docker:

```bash
cd frontend && npm install && npm run dev
```

### Config (`backend/.env`)

| var | for |
|---|---|
| `DATABASE_URL` | Supabase transaction pooler, port `6543` |
| `USER_SECRET` | session/cookie signing (`openssl rand -hex 32`) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth sign-in |
| `SUPERADMIN_EMAILS` | comma-separated emails always granted admin, even with no members row |
| `INTAKE_TOKEN` | shared secret for `POST /api/intake/slack` |
| `JIRA_BASE_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN` | Jira Cloud API auth |
| `JIRA_WRITES_ENABLED` | off by default — reads always work, creating/transitioning issues is opt-in |
| `SLACK_BOT_TOKEN` / `SLACK_CHANNEL` | Slack posting |
| `SLACK_WRITES_ENABLED` | same opt-in guard as Jira |
| `EMAIL_ENABLED` / `GMAIL_SMTP_USER` / `GMAIL_SMTP_APP_PASSWORD` | the plan-reminder email |
| `PLAN_REMINDER_HOUR` | when the email nudge fires, in `TIMEZONE` |
| `WEEK_START` | `0` = Mon–Sun reporting weeks, `6` = Sun–Sat |
| `TIMEZONE` | `Asia/Kolkata` — every "today"/"this week" boundary in the app is computed in this zone, not UTC |

**Two Supabase gotchas:**
- **Percent-encode the password.** A `#` in it truncates the URL silently — `pa#ss` must be `pa%23ss`.
- **Prepared statements are off** (`prepare_threshold=None` in `core/database.py`) because the transaction pooler rotates server connections between statements.

## What it does

One FastAPI backend serves a Postgres-backed dashboard and a background
scheduler; one React SPA renders it. The product surface:

- **My Day** — plan the day, report progress against it, raise unplanned
  tickets. Task type, work type, due date, and summary are mandatory; task
  type and work type are a two-step taxonomy (pick the work type, then a
  task type scoped to it).
- **Weekly Plan** — a separate, ticket-free table: one action per person per
  week. New rows start "yet to start"; status can move to in progress /
  blocked / completed any day but never back; achievements are only
  recordable on Friday. New rows can only be added Monday (filing) or
  Friday (catching up on unplanned work). Everyone sees only their own
  week; admins/managers can view (not edit) anyone's.
- **Overview** — headline effort/ticket totals, busiest work-type areas,
  activity trend, due-date risk.
- **Work log** — every ticket, filterable, with inline status/task-type
  editing and delete (which also cancels the linked Jira issue).
- **Team members / member detail** — per-person workload, effort
  breakdowns, plan adherence, full ticket history.
- **Requests** — the request-pipeline streams (Content Requests, HC/HT,
  Technical Writing), merged so Content Assessments count as part of
  Content Requests rather than a separate stream, with ticket counts
  alongside effort.
- **Leaderboard** — effort and ticket counts per person, per stream.
- **Plan board** (admin/manager) — who's filed a plan and logged an update
  today, plus how many tickets each person created/closed.
- **Content requests** (admin) — a raw mirror of the Jira Content Requests
  board.
- **Admin** — members, task/question-type lookups, integration health and
  manual sync/retry/digest triggers.

## Jira and Slack integration

- **Jira**: reads are always on; writes (`JIRA_WRITES_ENABLED`) create and
  transition issues, carrying task type, customer, effort, due date, and
  question type as Jira custom fields. Editing a ticket's summary or task
  type after creation re-syncs those fields on the Jira issue, not just our
  own database. A periodic drift check flags tickets whose Jira issue has
  since been deleted (`jira_missing`) rather than silently dropping them.
- **Slack**: every entry gets posted into a per-day thread; a roll call
  posts who has/hasn't planned or updated; a weekly-plan digest posts who's
  filed/updated the week. All gated behind `SLACK_WRITES_ENABLED`.

### Scheduled jobs (`core/scheduler.py`, all times in `TIMEZONE`)

| job | schedule | does |
|---|---|---|
| Content requests sync | every 15 min | mirrors the Jira Content Requests board |
| Jira history sync | every 30 min | incremental pull of created/updated issues |
| Jira deletion check | every 2 hr | full re-fetch to flag issues deleted in Jira |
| Publish scheduled entries | every 1 min | releases plans/updates whose `post_at` has arrived |
| Jira write sweep | every 5 min | retries stranded `pending` Jira writes |
| Plan reminder email | `PLAN_REMINDER_HOUR`, Mon–Fri | nudges anyone without a plan filed |
| Plan / update digest | 10:30 / 19:30 daily | reposts each entry into Slack |
| Plan / update roll call | 11:05 / 19:35, Mon–Fri | who has/hasn't planned or updated today |
| Weekly plan status | 23:59 Mon / 23:59 Fri | who's filed / updated this week's plan |

## Layout

```
backend/
  core/          config · database · orm · users · deps · dates · scheduler
  api/           auth · members · entries · analytics · integrations
                 intake · export · weekly_plan
  services/      entries · analytics · publish · content_requests ·
                 export · weekly_plan
  integrations/  jira · slack · email
  schemas/       entries · weekly_plan
  scripts/       seed.py            # lookups + legacy import, idempotent
                 backfill_jira.py   # bulk/incremental Jira import
                 reconcile_jira.py  # read-only Jira drift report + jira_missing flagger
                 audit_totals.py
  migrations/    alembic, autogenerate only — edit core/orm.py, never write these by hand
  tests/         161 tests
frontend/src/
  routes/        Overview · MyDay · WeeklyPlan · WorkLog · Members ·
                 MemberDetail · Requests · Leaderboard · PlanBoard ·
                 ContentRequests · Analytics · Admin · Login
  components/    ui · Shell · PeriodPicker · DateField · SchedulePicker ·
                 StatusDialog · RankedBars · RichText · Donut ·
                 StreamSplit · WorkloadHeatmap · EffortDrilldown ·
                 SyncButton · TodayStrip
  hooks/         useApi · useAuth · usePeriod · useTheme · useJiraSync ·
                 useDataVersion
  richtext.ts    sanitizer backing RichText.tsx (bold/italic/bullet list only)
  theme.css      design tokens (see frontend/DESIGN_REFERENCE.md)
```

Schema changes go through Alembic only — edit `core/orm.py`, then
`make revision m="what changed"`, review the generated migration, and only
then `make migrate`. Nothing calls `create_all()`.

## Status

67 API endpoints, 161 backend tests, 13 SPA routes. Schema, OAuth, RBAC,
Jira sync (read and write), Slack posting, scheduled digests, and exports
are all live end to end.
