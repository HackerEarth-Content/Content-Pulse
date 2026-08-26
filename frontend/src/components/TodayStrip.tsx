import { Link, useLocation } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../hooks/useApi";
import type { CurrentUser } from "../types";

/** Today's plan/update state, on every page.
 *
 * The two "+ Plan / + Update" buttons used to sit in the header saying nothing.
 * This says whether *you* have filed yet — and, for a lead, who hasn't — with
 * the action attached to the sentence rather than floating beside it. Naming
 * the people matters: a count nobody can act on is worse than a list they can
 * chase.
 */
export function TodayStrip({ me }: { me: CurrentUser["member"] }) {
  const today = useApi(() => api.today(), []);
  const isLead = me?.role === "admin" || me?.role === "manager";
  // Already on the page the CTA would send you to — the link is redundant there.
  const onMyDay = useLocation().pathname === "/my-day";

  if (today.loading || !today.data) return null;
  const t = today.data;

  // Computed server-side. Inferring it from absence in `no_plan_yet` silently
  // read admins as "already planned", because they weren't in the list at all.
  const iPlanned = t.you.planned;
  const iUpdated = t.you.updated;

  const call = !me
    ? null
    : !iPlanned
      ? { to: "/my-day", label: "Plan your day", tone: "primary" as const }
      : !iUpdated
        ? { to: "/my-day", label: "Log today's progress", tone: "primary" as const }
        : { to: "/my-day", label: "Open my day", tone: "secondary" as const };

  const state = !me ? "none" : iUpdated ? "done" : iPlanned ? "planned" : "todo";

  return (
    <section className="today-strip" aria-label="Today">
      <span className={`today-dot today-dot--${state}`} />

      <span className="today-mine">
        {!me ? (
          <>Not linked to a team member — you can read, but not log work.</>
        ) : iUpdated ? (
          <>
            <strong>You're done for today.</strong> Plan filed and updated.
          </>
        ) : iPlanned ? (
          <>
            <strong>Your plan is in.</strong> No update logged yet.
          </>
        ) : (
          <>
            <strong>Today's plan isn't in.</strong> Due by 11:59am.
          </>
        )}
      </span>

      <span className="today-team">
        {t.awaiting_update.length ? (
          <span className="today-stat today-stat--warn" title={
            t.awaiting_update.map((m) => m.member).join(", ")
          }>
            <b className="mono">{t.awaiting_update.length}</b>
            <span> awaiting an update</span>
          </span>
        ) : null}
        {isLead && t.no_plan_yet.length ? (
          <span className="today-stat" title={t.no_plan_yet.map((m) => m.member).join(", ")}>
            <b className="mono">{t.no_plan_yet.length}</b>
            <span> yet to plan</span>
          </span>
        ) : null}
      </span>

      {call && !onMyDay ? (
        <Link className={`btn btn-${call.tone} btn-sm today-cta`} to={call.to}>
          {call.label}
        </Link>
      ) : null}
    </section>
  );
}
