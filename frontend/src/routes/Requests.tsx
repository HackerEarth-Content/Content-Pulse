import { useState } from "react";
import { api } from "../api";
import { CATEGORICAL } from "../charts";
import { Donut } from "../components/Donut";
import { RankedBars } from "../components/RankedBars";
import { Async, Card, SectionHeading, StatTile } from "../components/ui";
import { mins, num, pct } from "../format";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";

/** Content Tasks owns Overview, Work log and Analytics. This screen is the
 * request pipelines. `tce_subtask` is a Jira housekeeping type with no effort. */
const EXCLUDED = new Set(["content_task", "tce_subtask"]);

/** The top-level bifurcation, at three parts so the colours survive an
 * all-pairs contrast check. Everything else is a ranked bar. */
const GROUPS: { key: string; label: string; areas: string[] }[] = [
  { key: "requests", label: "Content Requests", areas: ["content_request"] },
  { key: "assessments", label: "Content Assessments", areas: ["content_assessment"] },
  {
    key: "programs",
    label: "Programs & Writing",
    areas: ["hc_request", "ht_request", "hc_ht_feasibility", "technical_writing"],
  },
];

export function Requests({ range }: { range: Range }) {
  const p = { from: range.from, to: range.to };
  const deps = [range.from, range.to];
  const areas = useApi(() => api.byArea(p), deps);
  const [area, setArea] = useState<string | null>(null);

  const rows = (areas.data ?? []).filter((a) => !EXCLUDED.has(a.area));
  const current = area ?? rows[0]?.area ?? null;

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
          const effort = list.reduce((s, r) => s + r.effort_minutes, 0);
          const tickets = list.reduce((s, r) => s + r.tasks, 0);
          const grouped = GROUPS.map((g, i) => ({
            key: g.key,
            label: g.label,
            colour: CATEGORICAL[i],
            value: list
              .filter((a) => g.areas.includes(a.area))
              .reduce((s, a) => s + a.effort_minutes, 0),
            tickets: list
              .filter((a) => g.areas.includes(a.area))
              .reduce((s, a) => s + a.tasks, 0),
          })).filter((g) => g.value > 0 || g.tickets > 0);

          const top = [...grouped].sort((a, b) => b.value - a.value)[0];
          const busiest = [...list].sort((a, b) => b.effort_minutes - a.effort_minutes)[0];

          return (
            <>
              <p className="insight">
                <strong>{mins(effort)}</strong> across <strong>{tickets}</strong> request
                tickets.
                {top ? (
                  <>
                    {" "}
                    <strong>{top.label}</strong> takes {pct(top.value / (effort || 1))} of it,
                  </>
                ) : null}
                {busiest ? (
                  <>
                    {" "}
                    and <strong>{busiest.label}</strong> is the single busiest area at{" "}
                    {mins(busiest.effort_minutes)} over {busiest.tasks} tickets
                    {busiest.tasks
                      ? ` — ${mins(Math.round(busiest.effort_minutes / busiest.tasks))} each`
                      : ""}
                    .
                  </>
                ) : null}
              </p>

              <div className="grid cols-2">
                <Card title="The three streams" sub="share of hours logged">
                  <Donut
                    slices={grouped.map((g) => ({
                      key: g.key,
                      label: g.label,
                      value: g.value,
                      colour: g.colour,
                    }))}
                    total={effort}
                    totalLabel="total effort"
                    format={(n) => mins(n)}
                  />
                </Card>

                <Card title="Every area" sub="hours — click one to drill in">
                  <RankedBars
                    items={list.map((a) => ({
                      key: a.area,
                      label: a.label,
                      value: a.effort_minutes,
                      sub: `${a.tasks} tickets`,
                    }))}
                    format={(n) => mins(n)}
                    onSelect={setArea}
                    selected={current}
                  />
                  <p className="hint">
                    Ranked rather than coloured: six brand hues can't stay distinguishable
                    for colourblind readers, so the label carries identity here.
                  </p>
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
      <SectionHeading title="Inside this area" color="var(--accent-indigo)" />
      <Async loading={summary.loading} error={summary.error} data={summary.data}>
        {(s) => (
          <>
            <p className="insight">
              <strong>{s.tasks}</strong> tickets, <strong>{mins(s.effort_minutes || null)}</strong>{" "}
              logged by <strong>{s.members}</strong>{" "}
              {s.members === 1 ? "person" : "people"}.{" "}
              {s.tasks
                ? `That's ${mins(Math.round(s.effort_minutes / s.tasks))} per ticket, `
                : ""}
              {pct(s.completion_rate)} done.
            </p>
            <div className="stat-row">
              <StatTile label="Tickets" value={num(s.tasks)} accent="var(--accent-aqua)" />
              <StatTile
                label="Effort logged"
                value={mins(s.effort_minutes || null)}
                accent="var(--accent-orange)"
              />
              <StatTile label="Done" value={pct(s.completion_rate)} sub={`${s.closed} closed`} />
              <StatTile label="Still open" value={num(s.open + s.in_progress + s.blocked)} />
              <StatTile label="People" value={num(s.members)} />
            </div>
          </>
        )}
      </Async>

      <div className="grid cols-2" style={{ marginTop: 12 }}>
        <Card title="Who worked on it" sub="hours in this area">
          <Async loading={members.loading} error={members.error} data={members.data}
                 empty={{ title: "Nobody logged work here" }}>
            {(list) => (
              <RankedBars
                items={list.map((r) => ({
                  key: String(r.member_id),
                  label: r.member,
                  value: r.effort_minutes,
                  sub: `${r.tasks} tickets`,
                }))}
                format={(n) => mins(n)}
              />
            )}
          </Async>
        </Card>

        <Card title="What was asked for" sub="Jira request types">
          <Async loading={requestTypes.loading} error={requestTypes.error}
                 data={requestTypes.data}
                 empty={{ title: "Jira records no request type here" }}>
            {(list) => (
              <RankedBars
                items={list.map((r) => ({
                  key: r.request_type,
                  label: r.request_type,
                  value: r.effort_minutes,
                  sub: `${r.tasks} tickets`,
                }))}
                format={(n) => mins(n)}
              />
            )}
          </Async>
        </Card>
      </div>

      <div className="grid cols-2" style={{ marginTop: 12 }}>
        <Card title="Customers" sub="Jira records this on Content Requests only">
          <Async loading={customers.loading} error={customers.error} data={customers.data}
                 empty={{ title: "No customer recorded",
                          hint: "Only Content Requests carry a customer in Jira." }}>
            {(list) => (
              <RankedBars
                items={list.slice(0, 10).map((c) => ({
                  key: c.customer,
                  label: c.customer,
                  value: c.effort_minutes,
                  sub: `${c.tasks} tickets`,
                }))}
                format={(n) => mins(n)}
              />
            )}
          </Async>
        </Card>
        <Card title="Aging" sub="open tickets by days since logged">
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
