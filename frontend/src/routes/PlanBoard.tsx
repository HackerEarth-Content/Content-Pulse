import { Link } from "react-router-dom";
import { api } from "../api";
import { Async, Card, SectionHeading, StatTile } from "../components/ui";
import { today } from "../format";
import { useApi } from "../hooks/useApi";

const initial = (name: string) => (name.slice(0, 1) || "?").toUpperCase();

/** One mark, one boolean — no combining plan+update into a single derived
 * color. What you see is exactly what the API says, nothing inferred. */
function Mark({ yes, label }: { yes: boolean; label: string }) {
  return (
    <span
      className={`pb-mark ${yes ? "pb-mark--yes" : "pb-mark--no"}`}
      title={label}
      aria-label={label}
    >
      {yes ? "✓" : "✗"}
    </span>
  );
}

/** Today only — did each person file a morning plan, did they log an
 * evening update. `TodayStrip` answers this as a count on every page; this
 * is the same day, named person by person. */
export function PlanBoard() {
  const on = today();
  const status = useApi(() => api.planDailyStatus({ from: on, to: on }), [on]);

  return (
    <>
      <SectionHeading title="Plan board" color="var(--accent-indigo)" />
      <p className="tab-blurb">
        Who's filed a plan and logged an update today. A ticket only ever
        touched in Jira doesn't count as a filed plan.
      </p>

      <Card title="Today" sub="plan and update marked separately">
        <Async
          loading={status.loading}
          error={status.error}
          data={status.data}
          empty={{ title: "No active members" }}
        >
          {(rows) => {
            const sorted = [...rows].sort((a, b) => a.member.localeCompare(b.member));
            const plannedCount = sorted.filter((r) => r.planned).length;
            const updatedCount = sorted.filter((r) => r.updated).length;
            return (
              <>
                <div className="stat-row pb-summary">
                  <StatTile label="Filed a plan" value={`${plannedCount}/${sorted.length}`} />
                  <StatTile label="Logged an update" value={`${updatedCount}/${sorted.length}`} />
                </div>
                <div className="plan-legend">
                  <span className="plan-legend-item">
                    <span className="pb-mark pb-mark--yes" aria-hidden="true">✓</span> yes
                  </span>
                  <span className="plan-legend-item">
                    <span className="pb-mark pb-mark--no" aria-hidden="true">✗</span> no
                  </span>
                </div>
                <div className="table-scroll sticky-col">
                  <table>
                    <thead>
                      <tr>
                        <th>Member</th>
                        <th className="num">Plan</th>
                        <th className="num">Update</th>
                        <th className="num">Created</th>
                        <th className="num">Closed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sorted.map((r) => (
                        <tr key={r.member_id}>
                          <td className="strong">
                            <Link className="tag wp-person" to={`/my-day?member_id=${r.member_id}`}>
                              <span className="wp-avatar" aria-hidden="true">{initial(r.member)}</span>
                              {r.member}
                            </Link>
                          </td>
                          <td className="num pb-cell">
                            <Mark yes={r.planned}
                                  label={`${r.member} · Plan ${r.planned ? "filed" : "not filed"}`} />
                          </td>
                          <td className="num pb-cell">
                            <Mark yes={r.updated}
                                  label={`${r.member} · Update ${r.updated ? "logged" : "not logged"}`} />
                          </td>
                          <td className="num">{r.created}</td>
                          <td className="num">{r.closed}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            );
          }}
        </Async>
      </Card>
    </>
  );
}
