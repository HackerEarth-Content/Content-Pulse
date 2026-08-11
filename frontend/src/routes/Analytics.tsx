import { useState } from "react";
import { api } from "../api";
import { Donut } from "../components/Donut";
import { EffortDrilldown } from "../components/EffortDrilldown";
import { RankedBars } from "../components/RankedBars";
import { WorkloadHeatmap } from "../components/WorkloadHeatmap";
import { Async, Card, SectionHeading, StatTile } from "../components/ui";
import { hours, mins, num, pct } from "../format";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";
import { bucketFor, bucketNoun, bucketTick, groupSeries } from "../series";

/** Named for their contents, with a sentence saying what the tab answers.
 *
 * These were phrased as questions — "What shipped", "Can we trust it" — which
 * read well but meant you had to open each one to find out what was in it. The
 * noun says where to go; the blurb says what you'll get. */
const TABS = [
  { key: "Delivery", blurb: "What was planned, what got reported on, and what closed." },
  { key: "Time & effort", blurb: "How long work takes end to end, and where the logged hours went." },
  { key: "Customers", blurb: "Who the work was for, and how much rides on the largest accounts." },
  { key: "Data quality", blurb: "What's missing from the records behind every other number here." },
] as const;
type Tab = (typeof TABS)[number]["key"];

const ORD = ["var(--ord-2)", "var(--ord-3)", "var(--ord-4)", "var(--ord-5)"];
const QUALITY_LABELS: Record<string, string> = {
  notes: "no notes", count: "no item count", customer: "no customer",
  question_type: "no question type", due_date: "no due date", effort: "no effort logged",
};

export function Analytics({ range }: { range: Range }) {
  const [tab, setTab] = useState<Tab>("Delivery");
  const p = { from: range.from, to: range.to };
  const deps = [range.from, range.to];

  const adherence = useApi(() => api.adherence(p), deps);
  const cycle = useApi(() => api.cycleTime(p), deps);
  const aging = useApi(() => api.aging(p), deps);
  const qualityMix = useApi(() => api.qualityMix(p), deps);
  const customers = useApi(() => api.byCustomer(p), deps);
  const questions = useApi(() => api.byQuestionType(p), deps);
  const quality = useApi(() => api.dataQuality(p), deps);
  const effort = useApi(() => api.effortBreakdown(p), deps);
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

      <div className="nav" style={{ width: "fit-content" }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`nav-link${tab === t.key ? " active" : ""}`}
            title={t.blurb}
            onClick={() => setTab(t.key)}
          >
            {t.key}
          </button>
        ))}
      </div>
      <p className="tab-blurb">{TABS.find((t) => t.key === tab)?.blurb}</p>

      {tab === "Delivery" && (
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
            <Card title="Priority & SLA" sub="how much of the work is high priority, and whether it met its SLA">
              <Async loading={qualityMix.loading} error={qualityMix.error} data={qualityMix.data}>
                {(qm) => (
                  <>
                    <div className="stat-row" style={{ marginBottom: 10 }}>
                      <StatTile label="SLA met" value={num(qm.sla_met)} accent="var(--accent-aqua)" />
                      <StatTile label="SLA missed" value={num(qm.sla_missed)} accent="var(--accent-red)" />
                      <StatTile label="SLA rate" value={pct(qm.sla_rate)}
                                sub="of tickets Jira actually rated" />
                    </div>
                    <RankedBars
                      items={qm.by_priority.map((r) => ({
                        key: r.key, label: r.key, value: r.tasks, sub: mins(r.effort_minutes),
                      }))}
                    />
                  </>
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

      {tab === "Time & effort" && (
        <>
          <Card
            title="Cycle time"
            sub="elapsed time from a ticket being raised in Jira to it being resolved — not time spent working on it"
          >
            <Async loading={cycle.loading} error={cycle.error} data={cycle.data}>
              {(c) => (
                <>
                  <div className="stat-row" style={{ marginBottom: 14 }}>
                    <StatTile label="Typical ticket" value={hours(c.median_hours)}
                              sub="half take less than this" accent="var(--accent-aqua)" />
                    <StatTile label="Slowest 10%" value={hours(c.p90_hours)}
                              sub="one in ten takes at least this long" />
                    <StatTile
                      label="Tickets measured"
                      value={`${num(c.closed_tasks)} of ${num(c.measured_of_closed)}`}
                      sub={c.coverage === null ? undefined : `${pct(c.coverage)} of finished work`}
                    />
                  </div>
                  {c.filed_retroactively > 0 ? (
                    <p className="insight">
                      <strong>{num(c.filed_retroactively)} tickets</strong> were created and
                      resolved within two minutes — filed once the work was already done. They
                      measure paperwork, not effort, so they're left out of the median above.
                    </p>
                  ) : null}
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

          <Card title="Where the effort went" sub="every logged minute, traceable to a ticket">
            <Async loading={effort.loading} error={effort.error} data={effort.data}>
              {(e) => <EffortDrilldown data={e} />}
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
          <Card title="By customer" sub="hours and tickets per customer, largest first">
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

          <Card title="Concentration" sub="what share of all work the largest accounts take — a high number means concentration risk">
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

      {tab === "Data quality" && (
        <Card title="Data quality" sub="fields left empty on the tickets behind every other number here">
          <Async loading={quality.loading} error={quality.error} data={quality.data}>
            {(q) => (
              <>
                <div className="stat-row" style={{ marginBottom: 14 }}>
                  <StatTile
                    label="Plans with no update"
                    value={num(q.plans_with_unreported_tasks)}
                    accent="var(--status-warning)"
                  />
                  <StatTile
                    label="On retired work types"
                    value={num(q.tasks_on_retired_task_types)}
                    sub="work types since retired from the list"
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
