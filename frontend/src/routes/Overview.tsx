import {
  Bar,
  CartesianGrid,
  Legend,
  Line,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Async, BarList, Card, SectionHeading, StatTile, StatusPill } from "../components/ui";
import { hours, num, pct, shortDate } from "../format";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";

const AXIS = { stroke: "var(--ink-3)", fontSize: 11 };

export function Overview({ range }: { range: Range }) {
  const p = { from: range.from, to: range.to };
  const summary = useApi(() => api.summary(p), [range.from, range.to]);
  const trend = useApi(() => api.trend(p), [range.from, range.to]);
  const members = useApi(() => api.byMember(p), [range.from, range.to]);
  const types = useApi(() => api.byTaskType(p), [range.from, range.to]);
  const due = useApi(() => api.dueRisk(p), [range.from, range.to]);
  const cycle = useApi(() => api.cycleTime(p), [range.from, range.to]);
  const open = useApi(() => api.openItems({ ...p, limit: 12 }), [range.from, range.to]);

  return (
    <>
      <SectionHeading title="This period" />
      <Async loading={summary.loading} error={summary.error} data={summary.data}>
        {(s) => (
          <div className="stat-row">
            <StatTile label="Tasks" value={num(s.tasks)} sub={`${s.members} people`} accent="var(--accent-blue)" />
            <StatTile label="Volume" value={num(s.volume)} sub="items produced" accent="var(--accent-indigo)" />
            <StatTile
              label="Completion"
              value={pct(s.completion_rate)}
              sub={`${s.closed} of ${s.tasks} done`}
              accent="var(--accent-aqua)"
            />
            <StatTile label="In progress" value={num(s.in_progress)} sub={`${s.open} still open`} accent="var(--accent-yellow)" />
            <StatTile label="Blocked" value={num(s.blocked)} accent="var(--accent-red)" />
            <StatTile label="Plans / updates" value={`${s.plans} / ${s.updates}`} sub="entries filed" />
          </div>
        )}
      </Async>

      <SectionHeading title="Activity" color="var(--accent-indigo)" />
      <Card>
        <Async loading={trend.loading} error={trend.error} data={trend.data}>
          {(rows) => (
            <ResponsiveContainer width="100%" height={230}>
              <ComposedChart data={rows} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke="var(--line)" vertical={false} />
                <XAxis dataKey="date" tickFormatter={shortDate} tickLine={false} axisLine={false} {...AXIS} />
                <YAxis tickLine={false} axisLine={false} {...AXIS} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    background: "var(--surface)",
                    border: "1px solid var(--line)",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  labelFormatter={shortDate}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="tasks" name="Tasks" fill="var(--accent-blue)" radius={[3, 3, 0, 0]} maxBarSize={26} />
                <Line
                  dataKey="closed"
                  name="Closed"
                  stroke="var(--accent-aqua)"
                  strokeWidth={2}
                  dot={false}
                  type="monotone"
                />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </Async>
      </Card>

      <div className="grid cols-2" style={{ marginTop: 12 }}>
        <Card title="By member" sub="tasks in this range">
          <Async
            loading={members.loading}
            error={members.error}
            data={members.data}
            empty={{ title: "No activity", hint: "Nobody filed anything in this range." }}
          >
            {(rows) => (
              <BarList items={rows.slice(0, 8).map((r) => ({ label: r.member, value: r.tasks }))} />
            )}
          </Async>
        </Card>

        <Card title="By work type" sub="tasks in this range">
          <Async
            loading={types.loading}
            error={types.error}
            data={types.data}
            empty={{ title: "No work types yet" }}
          >
            {(rows) => (
              <BarList
                items={rows
                  .slice(0, 8)
                  .map((r) => ({ label: r.task_type, value: r.tasks, color: "var(--accent-indigo)" }))}
              />
            )}
          </Async>
        </Card>
      </div>

      <SectionHeading title="Risk & timing" color="var(--accent-yellow)" />
      <div className="grid cols-2">
        <Card title="Due dates" sub="open tasks only">
          <Async loading={due.loading} error={due.error} data={due.data}>
            {(d) => (
              <div className="stat-row">
                <StatTile label="Overdue" value={num(d.overdue)} accent="var(--status-critical)" />
                <StatTile label="Due today" value={num(d.due_today)} accent="var(--status-warning)" />
                <StatTile label="Due this week" value={num(d.due_this_week)} />
                <StatTile label="No due date" value={num(d.no_due_date)} />
              </div>
            )}
          </Async>
        </Card>

        <Card title="Cycle time" sub="open → done, from the status log">
          <Async loading={cycle.loading} error={cycle.error} data={cycle.data}>
            {(c) => (
              <>
                <div className="stat-row">
                  <StatTile label="Median" value={hours(c.median_hours)} accent="var(--accent-aqua)" />
                  <StatTile label="90th pct" value={hours(c.p90_hours)} />
                  <StatTile label="Closed" value={num(c.closed_tasks)} />
                </div>
                {c.median_hours === 0 ? (
                  <p className="hint">
                    Zero because imported history has no transitions — real numbers accrue from
                    tasks closed in this app.
                  </p>
                ) : null}
              </>
            )}
          </Async>
        </Card>
      </div>

      <SectionHeading
        title="Open work"
        color="var(--accent-orange)"
        action={
          <Link to="/work-log" className="section-action" style={{ textDecoration: "none" }}>
            Full work log →
          </Link>
        }
      />
      <Async
        loading={open.loading}
        error={open.error}
        data={open.data}
        empty={{ title: "Nothing open", hint: "Every task in this range is done." }}
      >
        {(rows) => (
          <div className="table-scroll">
            <table className="sticky-col">
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Task</th>
                  <th>Customer</th>
                  <th>Status</th>
                  <th className="num">Age</th>
                  <th>Due</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="strong">{r.member}</td>
                    <td>{r.task_type}</td>
                    <td className="muted">{r.customer ?? "—"}</td>
                    <td>
                      <StatusPill status={r.status} />
                    </td>
                    <td className="num">{r.age_days}d</td>
                    <td className={r.overdue ? "" : "muted"}>
                      {r.due_at ? (
                        r.overdue ? (
                          <span className="pill pill-blocked">{r.due_at}</span>
                        ) : (
                          r.due_at
                        )
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="cell-notes">{r.notes ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Async>
    </>
  );
}
