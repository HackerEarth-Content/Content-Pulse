import { useState } from "react";
import { api } from "../api";
import { Donut } from "../components/Donut";
import { RankedBars } from "../components/RankedBars";
import { WorkloadHeatmap } from "../components/WorkloadHeatmap";
import { Async, Card, SectionHeading, StatTile } from "../components/ui";
import { hours, mins, num, pct } from "../format";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";
import { bucketFor, bucketNoun, bucketTick, groupSeries } from "../series";

const TABS = ["What shipped", "How long it took", "Who it was for",
              "Can we trust it"] as const;
type Tab = (typeof TABS)[number];

const ORD = ["var(--ord-2)", "var(--ord-3)", "var(--ord-4)", "var(--ord-5)"];
const QUALITY_LABELS: Record<string, string> = {
  notes: "no notes", count: "no item count", customer: "no customer",
  question_type: "no question type", due_date: "no due date", effort: "no effort logged",
};

export function Analytics({ range }: { range: Range }) {
  const [tab, setTab] = useState<Tab>("What shipped");
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
        title="Insights"
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

      {tab === "What shipped" && (
        <>
          <Async loading={adherence.loading} error={adherence.error} data={adherence.data}>
            {(rows) => {
              const planned = rows.reduce((s, r) => s + r.planned, 0);
              const silent = rows.reduce((s, r) => s + r.no_update, 0);
              const worst = [...rows].sort((a, b) => b.no_update - a.no_update)[0];
              return (
                <p className="insight">
                  <strong>{planned}</strong> tasks planned,{" "}
                  <strong>{planned ? pct(1 - silent / planned) : "—"}</strong> reported on.
                  {silent
                    ? ` ${silent} were never updated${worst && worst.no_update ? `, ${worst.no_update} of them ${worst.member}'s` : ""}.`
                    : " Every one was followed up."}
                </p>
              );
            }}
          </Async>

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
                  <RankedBars
                    items={groupSeries(rows, bucket, ["closed"])
                      .filter((r) => r.closed > 0)
                      .map((r) => ({ key: r.date, label: bucketTick(r.date, bucket),
                                     value: r.closed }))}
                    showShare={false}
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
                  <RankedBars
                    items={rows.map((r) => ({ key: `${r.from}-${r.to}`,
                                              label: `${r.from} → ${r.to}`, value: r.count }))}
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

      {tab === "How long it took" && (
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
                    <RankedBars
                      items={c.by_member.map((m) => ({
                        key: m.member, label: m.member,
                        value: Math.round((m.median_hours ?? 0) * 60),
                        sub: `${m.closed_tasks} closed`,
                      }))}
                      format={(n) => mins(n)}
                      showShare={false}
                    />
                    <RankedBars
                      items={c.by_task_type.map((tt) => ({
                        key: tt.task_type, label: tt.task_type,
                        value: Math.round((tt.median_hours ?? 0) * 60),
                        sub: `${tt.closed_tasks} closed`,
                      }))}
                      format={(n) => mins(n)}
                      showShare={false}
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

      {tab === "Who it was for" && (
        <>
        <Async loading={customers.loading} error={customers.error} data={customers.data}>
          {(rows) => {
            const effort = rows.reduce((s, r) => s + r.effort_minutes, 0);
            const top3 = [...rows].sort((a, b) => b.effort_minutes - a.effort_minutes).slice(0, 3);
            const share = top3.reduce((s, r) => s + r.effort_minutes, 0) / (effort || 1);
            return (
              <p className="insight">
                <strong>{rows.length}</strong> customers,{" "}
                <strong>{mins(effort || null)}</strong> logged against them.
                {top3.length ? (
                  <>
                    {" "}The top three — {top3.map((r) => r.customer).join(", ")} — take{" "}
                    <strong>{pct(share)}</strong> of it.
                  </>
                ) : null}
              </p>
            );
          }}
        </Async>
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

          <Card title="Concentration" sub="how much rides on the biggest accounts">
            <Async loading={customers.loading} error={customers.error} data={customers.data}
                   empty={{ title: "No customer tagged" }}>
              {(rows) => {
                const sorted = [...rows].sort((a, b) => b.effort_minutes - a.effort_minutes);
                const top = sorted.slice(0, 2);
                const rest = sorted.slice(2);
                return (
                  <Donut
                    slices={[
                      ...top.map((r) => ({ key: r.customer, label: r.customer,
                                           value: r.effort_minutes })),
                      { key: "rest", label: `Everyone else (${rest.length})`,
                        value: rest.reduce((s, r) => s + r.effort_minutes, 0) },
                    ]}
                    totalLabel="customer effort"
                    format={(n) => mins(n)}
                  />
                );
              }}
            </Async>
          </Card>
        </div>

        <div style={{ marginTop: 12 }}>
          <Card title="Question types" sub="what the team builds">
            <Async loading={questions.loading} error={questions.error} data={questions.data}
                   empty={{ title: "No question types tagged" }}>
              {(rows) => (
                <RankedBars
                  items={rows.map((r) => ({ key: r.question_type, label: r.question_type,
                                            value: r.tasks, sub: `${r.volume} items` }))}
                />
              )}
            </Async>
          </Card>
        </div>
        </>
      )}

      {tab === "Can we trust it" && (
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
                <RankedBars
                  items={Object.entries(q.missing).map(([k, v]) => ({
                    key: k, label: QUALITY_LABELS[k] ?? k.replace(/_/g, " "), value: v,
                    sub: `${Math.round((v / (q.tasks || 1)) * 100)}% of tickets`,
                  }))}
                  max={q.tasks || 1}
                  showShare={false}
                />
              </>
            )}
          </Async>
        </Card>
      )}
    </>
  );
}
