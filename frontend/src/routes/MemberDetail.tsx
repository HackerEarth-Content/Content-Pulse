import { useParams } from "react-router-dom";
import { api } from "../api";
import { StatusDialog } from "../components/StatusDialog";
import { Async, BarList, Card, KindPill, SectionHeading, StatTile, StatusPill } from "../components/ui";
import { hours, num, pct, statusLabel } from "../format";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";
import type { Item } from "../types";
import { useState } from "react";

export function MemberDetail({ range }: { range: Range }) {
  const memberId = Number(useParams().id);
  const p = { from: range.from, to: range.to, member_id: memberId };
  const deps = [memberId, range.from, range.to];
  const [moving, setMoving] = useState<Item | null>(null);

  const members = useApi(() => api.members({ is_active: undefined }), []);
  const stats = useApi(() => api.byMember(p), deps);
  const adherence = useApi(() => api.adherence(p), deps);
  const cycle = useApi(() => api.cycleTime(p), deps);
  const types = useApi(() => api.byTaskType(p), deps);
  const entries = useApi(() => api.entries({ ...p, page_size: 100 }), deps);

  const member = (members.data ?? []).find((m) => m.id === memberId);
  const stat = (stats.data ?? [])[0];
  const adhere = (adherence.data ?? [])[0];

  return (
    <>
      <SectionHeading title={member?.display_name ?? `Member ${memberId}`} />

      {member ? (
        <p className="hint" style={{ marginTop: -6, marginBottom: 12 }}>
          <span className="pill pill-muted">{member.role}</span>{" "}
          {member.email ?? "no email on file — can't sign in yet"}
        </p>
      ) : null}

      <div className="stat-row">
        <StatTile label="Tasks" value={num(stat?.tasks ?? 0)} accent="var(--accent-blue)" />
        <StatTile label="Volume" value={num(stat?.volume ?? 0)} accent="var(--accent-indigo)" />
        <StatTile label="Completion" value={pct(stat?.completion_rate)} accent="var(--accent-aqua)" />
        <StatTile label="Open" value={num(stat?.open ?? 0)} />
        <StatTile label="Blocked" value={num(stat?.blocked ?? 0)} accent="var(--accent-red)" />
        <StatTile
          label="Median cycle"
          value={hours(cycle.data?.median_hours)}
          sub={`${cycle.data?.closed_tasks ?? 0} closed`}
        />
      </div>

      <div className="grid cols-2" style={{ marginTop: 12 }}>
        <Card title="Plan adherence" sub="planned → reported → closed">
          <Async loading={adherence.loading} error={adherence.error} data={adhere ? [adhere] : null}
                 empty={{ title: "No plans in this range" }}>
            {() => (
              <div className="stat-row">
                <StatTile label="Planned" value={num(adhere.planned)} />
                <StatTile label="Reported" value={num(adhere.reported)} sub={pct(adhere.report_rate)} />
                <StatTile label="Closed" value={num(adhere.closed)} sub={pct(adhere.close_rate)} />
                <StatTile
                  label="Never updated"
                  value={num(adhere.no_update)}
                  accent={adhere.no_update ? "var(--status-warning)" : undefined}
                />
              </div>
            )}
          </Async>
        </Card>

        <Card title="Work types" sub="tasks in this range">
          <Async loading={types.loading} error={types.error} data={types.data}
                 empty={{ title: "Nothing logged" }}>
            {(rows) => (
              <BarList
                items={rows.map((r) => ({ label: r.task_type, value: r.tasks, color: "var(--accent-indigo)" }))}
              />
            )}
          </Async>
        </Card>
      </div>

      <SectionHeading title="Entries" color="var(--accent-orange)" />
      <Async
        loading={entries.loading}
        error={entries.error}
        data={entries.data}
        empty={{ title: "Nothing logged in this range" }}
      >
        {(page) =>
          page.items.length === 0 ? (
            <div className="empty">
              <span className="empty-title">Nothing logged in this range</span>
              Try a wider date range.
            </div>
          ) : (
            <div className="table-scroll">
              <table className="sticky-col">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Kind</th>
                    <th>Work type</th>
                    <th>Customer</th>
                    <th className="num">Count</th>
                    <th>Status</th>
                    <th>Due</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.flatMap((entry) =>
                    entry.items.map((item) => (
                      <tr key={item.id}>
                        <td className="mono strong">{entry.entry_date}</td>
                        <td>
                          <KindPill kind={entry.kind} />
                        </td>
                        <td>{item.task_type}</td>
                        <td className="muted">{item.customer ?? "—"}</td>
                        <td className="num">{num(item.count)}</td>
                        <td>
                          {entry.kind === "update" && item.plan_item_id === null ? (
                            <StatusPill status={item.status} />
                          ) : (
                            <button
                              className={`pill pill-${item.status} pill-button`}
                              onClick={() => setMoving(item)}
                              title="Move status"
                            >
                              {statusLabel(item.status)}
                            </button>
                          )}
                        </td>
                        <td className="mono muted">{item.due_at ?? "—"}</td>
                        <td className="cell-notes">{item.notes ?? "—"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )
        }
      </Async>

      {moving ? (
        <StatusDialog item={moving} onClose={() => setMoving(null)} onSaved={entries.reload} />
      ) : null}
    </>
  );
}
