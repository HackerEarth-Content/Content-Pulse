# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: HackerEarth's content team (setters/reviewers) who plan their day,
log progress against tickets, and review their own effort/tickets weekly.
Secondary, confirmed: managers and admins who review team-wide workload,
plan adherence, and delivery health — and leadership/other teams outside the
content org who view the dashboard in reviews, not just the content team
itself. So the surface is read both as a fast daily-driver tool and as a
reporting surface an outside audience judges on sight.

## Product Purpose

ContentPulse (internally "ContentOps") is a daily plan/update tracker and
Jira/Slack dashboard for the content team: it replaces ad-hoc planning and
reporting with one system of record for what each person is working on,
what they said they'd do, and what actually got delivered — plus health
signals for the question library itself (candidate usage, feedback,
topic coverage).

## Positioning

Ties day-level planning (My Day), week-level commitment (Weekly Plan —
one action per person per week, status can't move backward, achievements
only recordable Friday), and after-the-fact delivery data (Jira-synced
tickets, effort, request streams) into one accountable loop, rather than
three disconnected tools (a planning doc, a standup, and a Jira board).

## Operating Context

- FastAPI + Postgres (Supabase) backend, React SPA frontend.
- Data sources: Jira Cloud API (tickets, request streams), Slack (posting),
  Redash (HE metrics — Content Health page), a legacy Django SQLite import.
- Reporting weeks/dates are computed in `Asia/Kolkata`, not UTC — a durable
  constraint on any date/time UI.
- Role model: member / manager / admin. Managers can view (not edit)
  anyone's weekly plan; some routes (Analytics, Requests, Plan board,
  Admin) are role-gated.
- Everything is behind Google OAuth sign-in — there is no signed-out view.

## Capabilities and Constraints

Confirmed screens (see README for full list): My Day, Weekly Plan,
Overview, Work log, Team members/detail, Requests (Content Requests,
HC/HT, Technical Writing), Leaderboard, Plan board, Content Health,
Content Issue Analysis, Skill Graph, Admin, Utils (MCQ Reviewer, Skill
Taxonomy).

Existing data-visualization components already in the frontend
(Recharts-based): `Donut`, `RankedBars`, `StreamSplit`, `WorkloadHeatmap`,
`EffortDrilldown`, plus a skill-rating radar on Content Health. Most charts
currently render with `isAnimationActive={false}` — no entrance/transition
motion.

## Brand Commitments

Visual identity is anchored to HackerEarth's production brand palette,
confirmed to keep as-is: `--accent-blue #0939e6`, indigo `#5f59ff`, orange
`#ff5722`, aqua `#1baf7a`, yellow `#eda100`, red `#e34948`, magenta
`#e87ba4`, plus a fixed-hue status ramp (good/warning/serious/critical/
neutral) and a fixed skill-rating ramp — these hues are intentionally
un-themed because they encode meaning (status, lifecycle, rating level)
that must read the same in light and dark. Logo: HackerEarth mark, swapped
per theme (`/hackerearth_logo.png` / `/hackerearth_logo_light.png`).
Redesign should keep these brand hues as the anchor and elevate layout,
depth, typography, chart richness, and motion around them — not replace
the palette.

## Evidence on Hand

Full existing frontend implementation at `frontend/src/` (React + Vite +
TypeScript + Recharts + react-router). Existing design system already
documents a WCAG AA–verified light/dark tonal ladder in
`frontend/src/theme.css` and a large `App.css` (~2,650 lines). No
DESIGN.md yet — this predates Impeccable's involvement; `document` was not
run first because the ask is a redesign, and the current look is being
treated as evidence/anti-reference for that redesign, not preserved as-is.

## Product Principles

- Accountability loop first: every visual choice should make "what's
  planned vs. what happened" easier to read at a glance, not just prettier.
- Dual audience: must work as a fast, low-friction daily tool for the
  content team and as a polished reporting surface for outside viewers —
  never trade daily-driver speed for spectacle.
- Status/lifecycle color meaning is sacred: never let a "richer" palette
  blur good/warning/serious/critical or the ordinal/rating ramps.
- Real data, real density: this dashboard reports on named people's real
  work; no decorative content, invented metrics, or empty placeholder
  polish.

## Accessibility & Inclusion

Existing tonal ladder is WCAG AA–verified (4.5:1 ink/surface pairs,
including status-chip ink-on-tint pairs) per in-code comments in
`theme.css`. `prefers-reduced-motion` is already respected for existing
transitions. Any new motion work must preserve both.
