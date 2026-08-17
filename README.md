# ContentOps

Daily plan/update tracker for the content team. FastAPI + Postgres + React.
Migration plan and full scope: [PLAN.md](PLAN.md).

## Run it

Postgres is hosted on Supabase; only the API and SPA run locally.

```bash
cp backend/.env.example backend/.env    # fill the DB URLs, USER_SECRET, Google keys
make migrate && make seed
make up
```

- API — http://localhost:8000 (`/docs`)
- SPA — http://localhost:5173

| command | does |
|---|---|
| `make up` / `make down` | start / stop |
| `make migrate` | `alembic upgrade head` |
| `make revision m="…"` | autogenerate a migration from `core/orm.py` |
| `make seed` | lookups + import the legacy Django SQLite (idempotent) |
| `make test` | pytest |

Backend without Docker:

```bash
cd backend && uv sync && uv run uvicorn main:app --reload
```

### Two Supabase gotchas

- **Percent-encode the password.** A `#` in it truncates the URL silently —
  `pa#ss` must be `pa%23ss`.
- **Two URLs, two ports.** `DATABASE_URL` uses the transaction pooler (6543)
  and runs with prepared statements off; `DIRECT_URL` uses the session pooler
  (5432) because Alembic's DDL and locks don't survive transaction pooling.

## Layout

```
backend/
  core/          config · database · orm · users · deps · dates · scheduler
  api/           auth · members · entries · ae · analytics · integrations
                 intake · exports
  services/      entries · analytics · ae · content_requests · export
  integrations/  jira · slack
  scripts/       seed.py            # lookups + legacy import, idempotent
  migrations/    alembic, autogenerate only
  tests/
frontend/src/
  routes/        Overview · WorkLog · Analytics · PlanForm · UpdateForm
                 Members · AEDaily · ContentRequests · Login
  components/    ui.tsx · Header · PeriodPicker
  hooks/         useApi · useAuth · useTheme · usePeriod
  theme.css      design tokens (see frontend/DESIGN_REFERENCE.md)
```

Schema changes go through Alembic only — edit `core/orm.py`, then
`make revision m="what changed"`. Nothing calls `create_all()`.

## Status

Working end to end: 48 API routes, 87 tests, 9 SPA screens.

| Area | State |
|---|---|
| Schema, migrations, legacy import | done — 9 members, 11 entries, 23 items |
| Google OAuth, `ALLOWED_EMAILS` gate | done — everything is behind sign-in |
| Entries, plan→update linkage, status log | done |
| Analytics (17 aggregates) and exports | done |
| Slack (bot token verified) | done |
| Jira | code done; **the API token 401s and needs regenerating** |
| Member ↔ Google account linking | pending — members have no email set |

`git` is not initialised in this directory yet.
