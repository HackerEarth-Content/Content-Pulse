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
import { AXIS as CHART_AXIS, TOOLTIP } from "../charts";
import { Donut } from "../components/Donut";
import { RankedBars } from "../components/RankedBars";
import { Async, Card, SectionHeading, StatTile, StatusPill } from "../components/ui";
import { hours, mins, num, pct } from "../format";
import { bucketFor, bucketNoun, bucketTick, groupSeries } from "../series";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";

const AXIS = CHART_AXIS;

export function Overview({ range }: { range: Range }) {
  const p = { from: range.from, to: range.to };
  const summary = useApi(() => api.summary(p), [range.from, range.to]);
  const trend = useApi(() => api.trend(p), [range.from, range.to]);
  const members = useApi(() => api.byMember(p), [range.from, range.to]);
  const types = useApi(() => api.byTaskType(p), [range.from, range.to]);
  const due = useApi(() => api.dueRisk(p), [range.from, range.to]);
  const cycle = useApi(() => api.cycleTime(p), [range.from, range.to]);
  const open = useApi(() => api.openItems({ ...p, limit: 12 }), [range.from, range.to]);
  const areas = useApi(() => api.byArea(p), [range.from, range.to]);

  // A quarter is ~92 daily points — roll up so the axis stays readable.
  const bucket = bucketFor(range.from, range.to);
  const trendRows = groupSeries(trend.data ?? [], bucket, ["tasks", "volume", "closed", "plans", "updates"]);

  return (
    <>
      <SectionHeading title="This period" />
      <Async loading={summary.loading} error={summary.error} data={summary.data}>
        {(s) => (
          <>
          <p className="insight">
            <strong>{num(s.tasks)}</strong> tickets and{" "}
            <strong>{mins(s.effort_minutes || null)}</strong> logged by{" "}
            <strong>{s.members}</strong> {s.members === 1 ? "person" : "people"}.{" "}
            {s.tasks
              ? `${mins(Math.round(s.effort_minutes / s.tasks))} per ticket on average, `
              : ""}
            {pct(s.completion_rate)} closed
            {s.blocked ? `, ${s.blocked} blocked` : ""}.
          </p>
          <div className="stat-row stat-row--bare">
            <StatTile label="Tasks" value={num(s.tasks)} sub={`logged by ${s.members} ${s.members === 1 ? "person" : "people"}`} accent="var(--accent-blue)" />
            <StatTile
              label="Items produced"
              value={num(s.volume)}
              sub="sum of the Count column"
              accent="var(--accent-indigo)"
            />
            <StatTile
              label="Completion"
              value={pct(s.completion_rate)}
              sub={`${s.closed} of ${s.tasks} done`}
              accent="var(--accent-aqua)"
            />
            <StatTile label="In progress" value={num(s.in_progress)} sub={`${s.open} still open`} accent="var(--accent-yellow)" />
            <StatTile label="Blocked" value={num(s.blocked)} accent="var(--accent-red)" />
            <StatTile
              label="Effort logged"
              value={mins(s.effort_minutes || null)}
              sub="time recorded on tasks"
              accent="var(--accent-orange)"
            />
            <StatTile label="Plans / updates" value={`${s.plans} / ${s.updates}`} sub="entries filed" />
          </div>
          </>
        )}
      </Async>

      <SectionHeading title="Where the effort goes" color="var(--accent-magenta)" />
      <div className="grid cols-2">
        <Card title="Task work vs requests" sub="share of hours">
          <Async loading={areas.loading} error={areas.error} data={areas.data}>
            {(list) => {
              const tasks = list.find((a) => a.area === "content_task");
              const requests = list.filter(
                (a) => !["content_task", "tce_subtask"].includes(a.area));
              const reqEffort = requests.reduce((s2, a) => s2 + a.effort_minutes, 0);
              return (
                <Donut
                  slices={[
                    { key: "content_task", label: "Content Tasks",
                      value: tasks?.effort_minutes ?? 0 },
                    { key: "requests", label: "Requests & Programs", value: reqEffort },
                  ]}
                  totalLabel="total effort"
                  format={(n) => mins(n)}
                />
              );
            }}
          </Async>
        </Card>
        <Card title="Busiest areas" sub="hours logged">
          <Async loading={areas.loading} error={areas.error} data={areas.data}>
            {(list) => (
              <RankedBars
                items={list.map((a) => ({ key: a.area, label: a.label,
                                          value: a.effort_minutes, sub: `${a.tasks} tickets` }))}
                format={(n) => mins(n)}
              />
            )}
          </Async>
        </Card>
      </div>

      <SectionHeading title="Activity" color="var(--accent-indigo)" />
      <Card sub={`per ${bucketNoun(bucket)}`}>
        <Async loading={trend.loading} error={trend.error} data={trend.data}>
          {() => (
            <ResponsiveContainer width="100%" height={230}>
              <ComposedChart data={trendRows} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke="var(--line)" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={(d) => bucketTick(d, bucket)}
                  tickLine={false}
                  axisLine={false}
                  interval="preserveStartEnd"
                  minTickGap={28}
                  {...AXIS}
                />
                <YAxis tickLine={false} axisLine={false} {...AXIS} allowDecimals={false} />
                <Tooltip
                  contentStyle={TOOLTIP}
                  labelFormatter={(d) => bucketTick(String(d), bucket)}
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
        <Card title="By member" sub="hours in this range">
          <Async
            loading={members.loading}
            error={members.error}
            data={members.data}
            empty={{ title: "No activity", hint: "Nobody filed anything in this range." }}
          >
            {(rows) => (
              <RankedBars
                items={rows.slice(0, 8).map((r) => ({
                  key: String(r.member_id), label: r.member,
                  value: r.effort_minutes, sub: `${r.tasks} tickets`,
                }))}
                format={(n) => mins(n)}
              />
            )}
          </Async>
        </Card>

        <Card title="By work type" sub="hours in this range">
          <Async
            loading={types.loading}
            error={types.error}
            data={types.data}
            empty={{ title: "No work types yet" }}
          >
            {(rows) => (
              <RankedBars
                items={rows.slice(0, 8).map((r) => ({
                  key: r.task_type, label: r.task_type,
                  value: r.effort_minutes, sub: `${r.tasks} tickets`,
                }))}
                format={(n) => mins(n)}
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
