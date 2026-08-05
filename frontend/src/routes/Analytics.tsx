import { useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { api } from "../api";
import { WorkloadHeatmap } from "../components/WorkloadHeatmap";
import { Async, BarList, Card, SectionHeading, StatTile } from "../components/ui";
import { hours, num, pct } from "../format";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";
import { bucketFor, bucketNoun, bucketTick, groupSeries } from "../series";

const TABS = ["Delivery", "Timing", "Customers", "Quality"] as const;
type Tab = (typeof TABS)[number];

const ORD = ["var(--ord-2)", "var(--ord-3)", "var(--ord-4)", "var(--ord-5)"];

export function Analytics({ range }: { range: Range }) {
  const [tab, setTab] = useState<Tab>("Delivery");
  const p = { from: range.from, to: range.to };
  const deps = [range.from, range.to];

  const adherence = useApi(() => api.adherence(p), deps);
  const cycle = useApi(() => api.cycleTime(p), deps);
  const aging = useApi(() => api.aging(p), deps);
  const flow = useApi(() => api.statusFlow(p), deps);
  const customers = useApi(() => api.byCustomer(p), deps);
  const questions = useApi(() => api.byQuestionType(p), deps);
  const quality = useApi(() => api.dataQuality(p), deps);
  const throughput = useApi(() => api.throughput(p), deps);
  const workload = useApi(() => api.workload(p), deps);
  const bucket = bucketFor(range.from, range.to);

  return (
    <>
      <SectionHeading
        title="Analytics"
        color="var(--accent-magenta)"
        action={
          <button className="section-action" onClick={() => api.exportAnalytics(p)}>
            Download workbook
          </button>
        }
      />

      <div className="nav" style={{ marginBottom: 14, width: "fit-content" }}>
        {TABS.map((t) => (
          <button
            key={t}
            className={`nav-link${tab === t ? " active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Delivery" && (
        <>
          <Card
            title="Plan adherence"
            sub="of what was planned, how much got reported on and how much closed"
          >
            <Async
              loading={adherence.loading}
              error={adherence.error}
              data={adherence.data}
              empty={{ title: "No plans in this range" }}
            >
              {(rows) => (
                <div className="table-scroll" style={{ border: 0, boxShadow: "none" }}>
                  <table className="sticky-col">
                    <thead>
                      <tr>
                        <th>Member</th>
                        <th className="num">Planned</th>
                        <th className="num">Reported</th>
                        <th className="num">Closed</th>
                        <th className="num">Never updated</th>
                        <th className="num">Report rate</th>
                        <th className="num">Close rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.member_id}>
                          <td className="strong">{r.member}</td>
                          <td className="num">{r.planned}</td>
                          <td className="num">{r.reported}</td>
                          <td className="num">{r.closed}</td>
                          <td className="num">
                            {r.no_update > 0 ? (
                              <span className="pill pill-in_progress">{r.no_update}</span>
                            ) : (
                              "0"
                            )}
                          </td>
                          <td className="num">{pct(r.report_rate)}</td>
                          <td className="num">{pct(r.close_rate)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Async>
          </Card>

          <div className="grid cols-2" style={{ marginTop: 12 }}>
            <Card title="Throughput" sub={`tasks closed per ${bucketNoun(bucket)}, from the status log`}>
              <Async loading={throughput.loading} error={throughput.error} data={throughput.data}>
                {(rows) => (
                  <BarList
                    items={groupSeries(rows, bucket, ["closed"])
                      .filter((r) => r.closed > 0)
                      .map((r) => ({
                        label: bucketTick(r.date, bucket),
                        value: r.closed,
                        color: "var(--accent-aqua)",
                      }))}
                  />
                )}
              </Async>
            </Card>
            <Card title="Status transitions" sub="blocked → open is the rework signal">
              <Async
                loading={flow.loading}
                error={flow.error}
                data={flow.data}
                empty={{ title: "No transitions yet", hint: "Statuses moved in this app will show here." }}
              >
                {(rows) => (
                  <BarList
                    items={rows.map((r) => ({
                      label: `${r.from} → ${r.to}`,
                      value: r.count,
                      color: r.to === "closed" ? "var(--accent-aqua)" : "var(--accent-orange)",
                    }))}
                  />
                )}
              </Async>
            </Card>
          </div>

          <div style={{ marginTop: 12 }}>
            <Card title="Workload" sub={`tasks per member per ${bucketNoun(bucket)}`}>
              <Async
                loading={workload.loading}
                error={workload.error}
                data={workload.data}
                empty={{ title: "Nothing logged in this range" }}
              >
                {(rows) => <WorkloadHeatmap rows={rows} bucket={bucket} />}
              </Async>
            </Card>
          </div>
        </>
      )}

      {tab === "Timing" && (
        <>
          <Card title="Cycle time" sub="open → done">
            <Async loading={cycle.loading} error={cycle.error} data={cycle.data}>
              {(c) => (
                <>
                  <div className="stat-row" style={{ marginBottom: 14 }}>
                    <StatTile label="Median" value={hours(c.median_hours)} accent="var(--accent-aqua)" />
                    <StatTile label="90th percentile" value={hours(c.p90_hours)} />
                    <StatTile label="Tasks measured" value={num(c.closed_tasks)} />
                  </div>
                  <div className="grid cols-2">
                    <BarList
                      items={c.by_member.map((m) => ({
                        label: m.member,
                        value: Math.round(m.median_hours ?? 0),
                      }))}
                    />
                    <BarList
                      items={c.by_task_type.map((t) => ({
                        label: t.task_type,
                        value: Math.round(t.median_hours ?? 0),
                        color: "var(--accent-indigo)",
                      }))}
                    />
                  </div>
                </>
              )}
            </Async>
          </Card>

          <Card title="Aging" sub="open tasks by days since they were logged">
            <Async loading={aging.loading} error={aging.error} data={aging.data}>
              {(a) => (
                <div className="stat-row">
                  {a.buckets.map((b, i) => (
                    <StatTile key={b.bucket} label={`${b.bucket} days`} value={num(b.tasks)} accent={ORD[i]} />
                  ))}
                </div>
              )}
            </Async>
          </Card>
        </>
      )}

      {tab === "Customers" && (
        <div className="grid cols-2">
          <Card title="By customer" sub="never aggregated in the old dashboard">
            <Async
              loading={customers.loading}
              error={customers.error}
              data={customers.data}
              empty={{ title: "No customer tagged", hint: "Add a customer on task rows to see this." }}
            >
              {(rows) => (
                <div className="table-scroll" style={{ border: 0, boxShadow: "none" }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Customer</th>
                        <th className="num">Tasks</th>
                        <th className="num">Items</th>
                        <th className="num">Outstanding</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.customer}>
                          <td className="strong">{r.customer}</td>
                          <td className="num">{r.tasks}</td>
                          <td className="num">{r.volume}</td>
                          <td className="num">{r.outstanding}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Async>
          </Card>

          <Card title="Question types" sub="share of tagged tasks">
            <Async
              loading={questions.loading}
              error={questions.error}
              data={questions.data}
              empty={{ title: "No question types tagged" }}
            >
              {(rows) => (
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={rows}
                      dataKey="tasks"
                      nameKey="question_type"
                      innerRadius={54}
                      outerRadius={92}
                      paddingAngle={2}
                    >
                      {rows.map((_, i) => (
                        <Cell key={i} fill={ORD[i % ORD.length]} stroke="var(--surface)" />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        background: "var(--surface)",
                        border: "1px solid var(--line)",
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </Async>
          </Card>
        </div>
      )}

      {tab === "Quality" && (
        <Card title="Data quality" sub="what's missing, and which plans nobody reported on">
          <Async loading={quality.loading} error={quality.error} data={quality.data}>
            {(q) => (
              <>
                <div className="stat-row" style={{ marginBottom: 14 }}>
                  <StatTile
                    label="Plans never reported"
                    value={num(q.plans_with_unreported_tasks)}
                    accent="var(--status-warning)"
                  />
                  <StatTile
                    label="On retired work types"
                    value={num(q.tasks_on_retired_task_types)}
                    sub="free text from the old app"
                  />
                  <StatTile label="Tasks in range" value={num(q.tasks)} />
                </div>
                <BarList
                  items={Object.entries(q.missing).map(([k, v]) => ({
                    label: `Missing ${k.replace(/_/g, " ")}`,
                    value: v,
                    color: "var(--accent-orange)",
                  }))}
                  max={q.tasks || 1}
                />
              </>
            )}
          </Async>
        </Card>
      )}
    </>
  );
}
