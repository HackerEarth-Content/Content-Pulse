import { Link } from "react-router-dom";
import { api } from "../api";
import { Async, BarList, Card, SectionHeading } from "../components/ui";
import { num, pct } from "../format";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";

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
                  <th className="num">Volume</th>
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
                        <Link className="tag" to={`/members/${m.id}`}>
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
      <div className="grid cols-2">
        <Card title="Tasks" sub="this range">
          <Async loading={stats.loading} error={stats.error} data={stats.data}>
            {(rows) => <BarList items={rows.map((r) => ({ label: r.member, value: r.tasks }))} />}
          </Async>
        </Card>
        <Card title="Volume" sub="items produced">
          <Async loading={stats.loading} error={stats.error} data={stats.data}>
            {(rows) => (
              <BarList
                items={rows.map((r) => ({
                  label: r.member,
                  value: r.volume,
                  color: "var(--accent-indigo)",
                }))}
              />
            )}
          </Async>
        </Card>
      </div>
    </>
  );
}
