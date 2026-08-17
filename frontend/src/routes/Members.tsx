import { Link } from "react-router-dom";
import { api } from "../api";
import { Async, SectionHeading } from "../components/ui";
import { mins, num, pct } from "../format";
import { useApi } from "../hooks/useApi";
import { rangeQuery, type Range } from "../hooks/usePeriod";

export function Members({ range }: { range: Range }) {
  const p = { from: range.from, to: range.to };
  const members = useApi(() => api.members({ is_active: true }), []);
  const stats = useApi(() => api.byMember(p), [range.from, range.to]);
  const adherence = useApi(() => api.adherence(p), [range.from, range.to]);

  const byId = new Map((stats.data ?? []).map((s) => [s.member_id, s]));
  const adherenceById = new Map((adherence.data ?? []).map((a) => [a.member_id, a]));

  return (
    <>
      <SectionHeading title="Team" />
      <Async
        loading={members.loading}
        error={members.error}
        data={members.data}
        empty={{ title: "No members yet" }}
      >
        {(rows) => (
          <div className="table-scroll">
            <table className="sticky-col">
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Role</th>
                  <th>Email</th>
                  <th className="num">Tasks</th>
                  <th className="num">Items</th>
                  <th className="num">Effort</th>
                  <th className="num">Open</th>
                  <th className="num">Blocked</th>
                  <th className="num">Completion</th>
                  <th className="num">Never updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((m) => {
                  const s = byId.get(m.id);
                  const a = adherenceById.get(m.id);
                  return (
                    <tr key={m.id}>
                      <td className="strong">
                        <Link className="tag" to={`/members/${m.id}?${rangeQuery(range)}`}>
                          {m.display_name}
                        </Link>
                      </td>
                      <td>
                        <span className="pill pill-muted">{m.role}</span>
                      </td>
                      <td className={m.email ? "muted" : ""}>
                        {m.email ?? <span className="pill pill-in_progress">not linked</span>}
                      </td>
                      <td className="num">{num(s?.tasks ?? 0)}</td>
                      <td className="num">{num(s?.volume ?? 0)}</td>
                      <td className="num">{mins(s?.effort_minutes || null)}</td>
                      <td className="num">{num(s?.open ?? 0)}</td>
                      <td className="num">{num(s?.blocked ?? 0)}</td>
                      <td className="num">{pct(s?.completion_rate)}</td>
                      <td className="num">{a?.no_update ? a.no_update : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Async>

      <p className="hint">
        Members without an email can't sign in — sign-in matches a Google account to a member by
        email address.
      </p>

      <SectionHeading title="Load" color="var(--accent-indigo)" />
      <Async loading={stats.loading} error={stats.error} data={stats.data}>
        {(rows) => {
          const effort = rows.reduce((s, r) => s + r.effort_minutes, 0);
          const sorted = [...rows].sort((a, b) => b.effort_minutes - a.effort_minutes);
          const half = sorted.slice(0, Math.max(1, Math.ceil(sorted.length / 2)));
          const halfShare = half.reduce((s, r) => s + r.effort_minutes, 0) / (effort || 1);
          return (
            <p className="insight">
              <strong>{mins(effort || null)}</strong> across{" "}
              <strong>{rows.length}</strong> people.
              {sorted[0] ? (
                <>
                  {" "}
                  <strong>{sorted[0].member}</strong> carries the most at{" "}
                  {mins(sorted[0].effort_minutes || null)}, and the busier half of the
                  team accounts for <strong>{pct(halfShare)}</strong> of all hours.
                </>
              ) : null}
            </p>
          );
        }}
      </Async>
      <p className="hint">
        Ranked by effort and ticket count — see the{" "}
        <Link className="tag" to={`/leaderboard?${rangeQuery(range)}`}>leaderboard →</Link>
      </p>
    </>
  );
}
