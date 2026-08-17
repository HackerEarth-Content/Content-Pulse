# Roles & per-user access — proposal

**Short answer: yes, build it — with one change to the shape you described.**

Two thirds of this is clearly right and fixes real problems you have today. The
remaining third — strict per-user data isolation — is the part worth arguing
about, because taken literally it removes most of what the dashboard is for.

---

## 1. What you asked for

| | |
|---|---|
| Super admins | 4 named email addresses, full control, can add users |
| Users | sign in with Gmail, see their own details, not other people's |
| Plan form | no member picker — it's already you |

## 2. What I'd change about it

**Two tiers isn't enough, and "only their own data" is too strict.**

Your team already has leads. With a binary split, a lead is either a super admin
(and can retire work types and post to Slack) or an ordinary user (and can't see
their own team). Neither is right.

And the substance of this app is comparison: plan adherence *across* people,
throughput *across* the team, who's blocked. If Shivendra signs in and sees only
Shivendra, the Overview is a single bar, Analytics has one row, and the thing
stops being a dashboard.

**Proposed instead — three tiers, and split "aggregate" from "row-level":**

| Tier | Team aggregates | Row-level detail | Writes | Admin |
|---|---|---|---|---|
| **admin** (4 emails) | all | all | anyone's | yes |
| **manager** | all | all | anyone's | no |
| **member** | **all** (counts, rates, charts) | **own only** | **own only** | no |

So an ordinary user still sees "the team closed 34 tasks, I closed 6, median
cycle time is 2 days" — but cannot read Niharika's notes, her customers, or her
per-task detail. That is the distinction that actually matters for privacy:
nobody minds being in a count, people mind their notes being read.

If you genuinely want members to see *nothing* but themselves, say so — it's a
one-line change in the scoping rule. I just don't think you'll like the result.

---

## 3. Merits

1. **Kills mis-attribution.** Today any signed-in person can file a plan as any
   member — the form is a free dropdown. Prefilling from the session makes the
   data trustworthy, which every number in `analytics.py` depends on.
2. **Adding a user stops being a deploy.** Right now access is `ALLOWED_EMAILS`
   in `.env`, so onboarding means editing a file and restarting the server. Make
   the `members` table the allowlist and a super admin adds a row in the Admin
   screen. This is the single biggest ops win here.
3. **Fewer clicks on the daily path.** Plan and update forms lose their first
   field. That's the screen people touch every day.
4. **Real privacy boundary.** Per-person performance data is sensitive; "closed
   1 of 9" next to someone's name is a performance review. Right now everyone
   who can sign in can read everyone's.
5. **It's mostly already plumbed.** `Scope.member_id` is threaded through all 17
   analytics aggregates, `members.user_id` and `role` exist, and
   `require_member(*roles)` is written. This is enforcement, not new machinery.
6. **Audit gets meaningful.** `created_by_user_id` is already stored on every
   entry but is null for imports and unused. With sessions bound to people it
   becomes a real trail.
7. **Un-lockout-able.** Sourcing the 4 super admins from env means a bad DB edit
   can never lock every admin out.

---

## 4. Demerits and risks

1. **Nobody can log in yet.** 0 of 11 members have an email. Until a super admin
   fills them in, everyone lands read-only — and the Admin screen that sets them
   is itself behind sign-in. Handled by the env-sourced super admins, who always
   resolve to an admin member even with no row. Worth knowing it's the first
   thing that has to happen.
2. **A missed endpoint is a data leak.** 36 of 55 routes return
   member-attributable data. Scoping applied per-route *will* eventually miss
   one. Mitigation: one `viewer` dependency that returns a forced filter, applied
   at the router level, plus a test that walks every route and asserts a member
   cannot read another member's row. This is the main engineering risk.
3. **The AE grid is inherently cross-member.** `/ae/daily` is a date × person
   comparison table — that's its whole purpose. Under strict scoping it collapses
   to one column. It has to be manager-and-above, or aggregate-only for members.
4. **Slack intake has no session.** `/api/intake/slack` is token-authenticated
   and writes as whichever member the payload names. It stays that way, which
   means the token can still write as anyone. Acceptable (it's a server-to-server
   secret), but it is a hole in "you can only write as yourself" and shouldn't be
   described as if it isn't.
5. **Imported history has no author.** All 11 imported entries have
   `created_by_user_id = null`, so "who logged this" is unanswerable for anything
   before today.
6. **A member with two accounts, or none.** Someone whose Google address differs
   from their work address silently gets no member link and lands read-only, with
   no obvious reason why. Needs a clear "your account isn't linked" state rather
   than an empty dashboard.
7. **More tests, more surface.** Roughly doubles the authorization test count.
   The alternative — not testing it — is how leaks ship.
8. **It's a one-way door socially.** Once people know the tool enforces
   per-person visibility, loosening it later reads as a privacy regression.

---

## 5. How it would work

### Identity and bootstrap

```
SUPERADMIN_EMAILS=a@hackerearth.com,b@…,c@…,d@…     # env, 4 addresses
```

On OAuth callback:
- email in `SUPERADMIN_EMAILS` → find-or-create their `members` row, force
  `role='admin'`, link `user_id`. Self-healing; they can never be locked out.
- otherwise → look up an **active** member by email. Found: link and sign in.
  Not found: reject with the existing `not_allowed` bounce.

`ALLOWED_EMAILS` is then deleted. **The members table becomes the allowlist**,
which is exactly "super admins can add new users and give them access".

### Scoping

One dependency, one rule:

```python
async def viewer(member = Depends(get_member)) -> Viewer:
    """`scope_member_id` is None for admin/manager, else forced to own id.
    Every route that returns row-level data takes this, not a raw query param."""
```

- `admin` / `manager` → `scope_member_id = None`, may pass any `member_id` filter
- `member` → `scope_member_id = own id`; a `member_id` param naming someone else
  is **ignored, not honoured** (403 would leak that the id exists)

Applied to: `/entries*`, `/analytics/*` row-level endpoints (`open-items`,
`workload`), `/ae/*`, all 5 exports. Aggregate endpoints keep team-wide numbers.

### Writes

`member_id` disappears from the request body. The server derives it from the
session; admins and managers may still pass one explicitly. Plan and update forms
lose their picker and show "Filing as **Shivendra**" instead.

### Roles

Reuse the existing `members.role` enum — `admin` is the super admin, `manager`
the middle tier, `content`/`ae` ordinary members. **No migration needed.**

---

## 6. Work

| # | | Effort |
|---|---|---|
| 1 | `SUPERADMIN_EMAILS`, bootstrap on callback, drop `ALLOWED_EMAILS` | 2h |
| 2 | `viewer` dependency + `Viewer` model | 2h |
| 3 | Apply to entries, AE, row-level analytics, exports | 4h |
| 4 | Derive `member_id` from session on writes | 2h |
| 5 | Restore role gating on admin routes (currently open — see the `ponytail:` note in `members_routes.py`) | 1h |
| 6 | Frontend: drop pickers, "filing as", hide Admin nav, unlinked-account state | 4h |
| 7 | Authorization tests, incl. a walk-every-route leak test | 4h |
| 8 | Super admin fills in 11 member emails | you |

**≈2.5 days.** Nothing here blocks on the Jira token.

---

## 7. Decisions I need

1. **The main one.** Do ordinary members see team *aggregates* (recommended) or
   literally nothing but themselves?
2. **The 4 super admin addresses.**
3. **Is there a manager tier**, and who's in it? If not, `manager` stays unused
   and leads become admins.
4. **Who sees the AE grid** — managers and above, or all AEs?
5. **Members without a Google address** — leave them as data-only rows that
   others file for (fine), or must every member be able to log in?
