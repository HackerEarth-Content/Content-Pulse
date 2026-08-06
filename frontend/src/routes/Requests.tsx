import { useState } from "react";
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { api } from "../api";
import { Async, BarList, Card, SectionHeading, StatTile } from "../components/ui";
import { mins, num, pct } from "../format";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";

/** Content Tasks is the day-to-day stream and owns Overview, Work log and
 * Analytics. This screen is the request pipelines. */
const EXCLUDED = new Set(["content_task", "tce_subtask"]);

const AREA_COLOURS: Record<string, string> = {
  content_request: "var(--accent-blue)",
  content_assessment: "var(--accent-indigo)",
  ht_request: "var(--accent-aqua)",
  hc_ht_feasibility: "var(--accent-yellow)",
  hc_request: "var(--accent-orange)",
  technical_writing: "var(--accent-magenta)",
};
const colourFor = (area: string) => AREA_COLOURS[area] ?? "var(--ink-3)";

export function Requests({ range }: { range: Range }) {
  const p = { from: range.from, to: range.to };
  const deps = [range.from, range.to];
  const areas = useApi(() => api.byArea(p), deps);
  const [active, setActive] = useState<string | null>(null);

  const rows = (areas.data ?? []).filter((a) => !EXCLUDED.has(a.area));
  const current = active ?? rows[0]?.area ?? null;

  return (
    <>
      <SectionHeading title="Requests" color="var(--accent-magenta)" />

      <Async
        loading={areas.loading}
        error={areas.error}
        data={rows.length ? rows : null}
        empty={{ title: "No request work in this range" }}
      >
        {(list) => {
          const tickets = list.reduce((s, r) => s + r.tasks, 0);
          const effort = list.reduce((s, r) => s + r.effort_minutes, 0);
          return (
            <>
              <div className="grid cols-2">
                <Card title="Split by area" sub="share of hours logged">
                  <ResponsiveContainer width="100%" height={260}>
                    <PieChart>
                      <Pie
                        data={list.map((a) => ({
                          name: a.label,
                          value: a.effort_minutes,
                          area: a.area,
                        }))}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={58}
                        outerRadius={96}
                        paddingAngle={2}
                        onClick={(d: { area?: string }) => d.area && setActive(d.area)}
                      >
                        {list.map((a) => (
                          <Cell key={a.area} fill={colourFor(a.area)} stroke="var(--surface)" />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(v: number) => mins(v)}
                        contentStyle={{
                          background: "var(--surface)",
                          border: "1px solid var(--line)",
                          borderRadius: 8,
                          fontSize: 12,
                        }}
                      />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                    </PieChart>
                  </ResponsiveContainer>
                </Card>

                <Card title="Areas" sub="click one to drill in">
                  <div className="table-scroll" style={{ border: 0, boxShadow: "none" }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Area</th>
                          <th className="num">Tickets</th>
                          <th className="num">Effort</th>
                          <th className="num">Share</th>
                        </tr>
                      </thead>
                      <tbody>
                        {list.map((a) => (
                          <tr
                            key={a.area}
                            onClick={() => setActive(a.area)}
                            style={{
                              cursor: "pointer",
                              background:
                                current === a.area
                                  ? `color-mix(in srgb, ${colourFor(a.area)} 10%, transparent)`
                                  : undefined,
                            }}
                          >
                            <td className="strong">
                              <span
                                className="area-dot"
                                style={{ background: colourFor(a.area) }}
                              />
                              {a.label}
                            </td>
                            <td className="num">{a.tasks}</td>
                            <td className="num">{mins(a.effort_minutes || null)}</td>
                            <td className="num">{pct(a.effort_minutes / (effort || 1))}</td>
                          </tr>
                        ))}
                        <tr>
                          <td className="strong">All requests</td>
                          <td className="num strong">{tickets}</td>
                          <td className="num strong">{mins(effort || null)}</td>
                          <td className="num strong">100%</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </Card>
              </div>

              {current ? <Area key={current} area={current} range={range} /> : null}
            </>
          );
        }}
      </Async>
    </>
  );
}

function Area({ area, range }: { area: string; range: Range }) {
  const p = { from: range.from, to: range.to, area };
  const deps = [area, range.from, range.to];

  const summary = useApi(() => api.summary(p), deps);
  const members = useApi(() => api.byMember(p), deps);
  const customers = useApi(() => api.byCustomer(p), deps);
  const requestTypes = useApi(() => api.byRequestType(p), deps);
  const aging = useApi(() => api.aging(p), deps);

  return (
    <>
      <SectionHeading title="This area" color="var(--accent-indigo)" />
      <Async loading={summary.loading} error={summary.error} data={summary.data}>
        {(s) => (
          <div className="stat-row">
            <StatTile label="Tickets" value={num(s.tasks)} accent="var(--accent-blue)" />
            <StatTile
              label="Effort logged"
              value={mins(s.effort_minutes || null)}
              accent="var(--accent-orange)"
            />
            <StatTile label="Done" value={pct(s.completion_rate)} sub={`${s.closed} of ${s.tasks}`}
                      accent="var(--accent-aqua)" />
            <StatTile label="Still open" value={num(s.open + s.in_progress + s.blocked)} />
            <StatTile label="People" value={num(s.members)} />
          </div>
        )}
      </Async>

      <div className="grid cols-2" style={{ marginTop: 12 }}>
        <Card title="Who worked on it">
          <Async loading={members.loading} error={members.error} data={members.data}
                 empty={{ title: "Nobody logged work here" }}>
            {(list) => (
              <div className="table-scroll" style={{ border: 0, boxShadow: "none" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Member</th>
                      <th className="num">Tickets</th>
                      <th className="num">Effort</th>
                      <th className="num">Done</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((r) => (
                      <tr key={r.member_id}>
                        <td className="strong">{r.member}</td>
                        <td className="num">{r.tasks}</td>
                        <td className="num">{mins(r.effort_minutes || null)}</td>
                        <td className="num">{pct(r.completion_rate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Async>
        </Card>

        <Card title="Request types" sub="what was actually asked for">
          <Async loading={requestTypes.loading} error={requestTypes.error} data={requestTypes.data}
                 empty={{ title: "Jira records no request type for this area" }}>
            {(list) => (
              <BarList
                items={list.map((r) => ({
                  label: r.request_type,
                  value: Math.round(r.effort_minutes / 60),
                  color: "var(--accent-indigo)",
                }))}
              />
            )}
          </Async>
        </Card>
      </div>

      <div className="grid cols-2" style={{ marginTop: 12 }}>
        <Card title="Customers" sub="Jira records this on Content Requests only">
          <Async loading={customers.loading} error={customers.error} data={customers.data}
                 empty={{ title: "No customer recorded" }}>
            {(list) => (
              <BarList
                items={list.slice(0, 10).map((c) => ({
                  label: c.customer,
                  value: Math.round(c.effort_minutes / 60),
                  color: "var(--accent-magenta)",
                }))}
              />
            )}
          </Async>
        </Card>
        <Card title="Aging" sub="open tickets by age">
          <Async loading={aging.loading} error={aging.error} data={aging.data}>
            {(a) => (
              <div className="stat-row">
                {a.buckets.map((b) => (
                  <StatTile key={b.bucket} label={`${b.bucket} days`} value={num(b.tasks)} />
                ))}
              </div>
            )}
          </Async>
        </Card>
      </div>
    </>
  );
}
