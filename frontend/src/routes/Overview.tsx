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
import { Async, Card, SectionHeading, StatTile } from "../components/ui";
import { hours, mins, num, pct } from "../format";
import { mergeAssessments } from "./Requests";
import { bucketFor, bucketNoun, bucketTick, groupSeries } from "../series";
import { useApi } from "../hooks/useApi";
import { rangeQuery, type Range } from "../hooks/usePeriod";

const AXIS = CHART_AXIS;

// Content Tasks, Creation and Review, and TCE Subtask are internal work
// buckets, not the requester-facing work types this breakdown is for.
const EXCLUDED_PIPELINES = ["content_task", "creation_and_review", "tce_subtask"];
const STAGE_COLORS = { open: "var(--accent-blue)", in_progress: "var(--accent-yellow)", blocked: "var(--accent-red)" } as const;

export function Overview({ range }: { range: Range }) {
  const p = { from: range.from, to: range.to };
  const summary = useApi(() => api.summary(p), [range.from, range.to]);
  const trend = useApi(() => api.trend(p), [range.from, range.to]);
  const types = useApi(() => api.byTaskType(p), [range.from, range.to]);
  const due = useApi(() => api.dueRisk(p), [range.from, range.to]);
  const cycle = useApi(() => api.cycleTime(p), [range.from, range.to]);
  const areas = useApi(() => api.byArea(p), [range.from, range.to]);
  const pipelines = useApi(() => api.byPipeline(p), [range.from, range.to]);

  // A quarter is ~92 daily points — roll up so the axis stays readable.
  const bucket = bucketFor(range.from, range.to);
  const trendRows = groupSeries(trend.data ?? [], bucket, ["tasks", "volume", "closed", "plans", "updates"]);

  return (
    <>
      <SectionHeading
        title="This period"
        action={
          <button className="section-action" onClick={() => api.exportOverview(p)}>
            Download workbook
          </button>
        }
      />
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
        <Card title="Busiest areas" sub="by work type">
          <Async loading={areas.loading} error={areas.error} data={areas.data}>
            {(list) => (
              <RankedBars
                items={mergeAssessments(list).map((a) => ({ key: a.area, label: a.label,
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

      <div className="grid cols-2">
        <Card title="By task type" sub="hours in this range">
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

        <Card title="Items produced by task type" sub="sum of the Count column, in this range">
          <Async
            loading={types.loading}
            error={types.error}
            data={types.data}
            empty={{ title: "No work types yet" }}
          >
            {(rows) => (
              <RankedBars
                items={[...rows].filter((r) => r.volume > 0)
                  .sort((a, b) => b.volume - a.volume).slice(0, 8)
                  .map((r) => ({
                    key: r.task_type, label: r.task_type,
                    value: r.volume, sub: `${r.tasks} tickets`,
                  }))}
                format={(n) => num(n)}
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

      <SectionHeading title="Active work by type" color="var(--accent-orange)" />
      <Card sub="open, in progress, and blocked tickets — closed excluded">
        <Async
          loading={pipelines.loading}
          error={pipelines.error}
          data={pipelines.data}
          empty={{ title: "No work types yet" }}
        >
          {(rows) => {
            const visible = rows.filter((r) => !EXCLUDED_PIPELINES.includes(r.pipeline));
            return (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: "30%" }}>Work type</th>
                      <th style={{ width: "15%" }}>Open</th>
                      <th style={{ width: "15%" }}>In progress</th>
                      <th style={{ width: "15%" }}>Blocked</th>
                      <th style={{ width: "25%" }}>Active breakdown</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((r) => {
                      const active = r.open + r.in_progress + r.blocked;
                      const peak = Math.max(1, r.open, r.in_progress, r.blocked);
                      return (
                        <tr key={r.pipeline}>
                          <td className="strong">{r.label}</td>
                          <td>{num(r.open)}</td>
                          <td>{num(r.in_progress)}</td>
                          <td>{num(r.blocked)}</td>
                          <td>
                            {active ? (
                              <div className="heatmap-row">
                                <div className="heatmap-bar" title={`Open: ${r.open}`}
                                     style={{ height: `${(r.open / peak) * 100}%`, background: STAGE_COLORS.open }} />
                                <div className="heatmap-bar" title={`In progress: ${r.in_progress}`}
                                     style={{ height: `${(r.in_progress / peak) * 100}%`, background: STAGE_COLORS.in_progress }} />
                                <div className="heatmap-bar" title={`Blocked: ${r.blocked}`}
                                     style={{ height: `${(r.blocked / peak) * 100}%`, background: STAGE_COLORS.blocked }} />
                              </div>
                            ) : (
                              <span className="hint">Nothing active</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            );
          }}
        </Async>
      </Card>

      <SectionHeading title="Open work" color="var(--accent-orange)" />
      <Async loading={summary.loading} error={summary.error} data={summary.data}>
        {(s) => (
          <p className="insight">
            <strong>{num(s.open)}</strong> {s.open === 1 ? "ticket is" : "tickets are"} still
            open.{" "}
            <Link className="tag" to={`/work-log?status=open&${rangeQuery(range)}`}>
              View them in the work log →
            </Link>
          </p>
        )}
      </Async>
    </>
  );
}
