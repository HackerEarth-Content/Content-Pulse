import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useParams } from "react-router-dom";
import { api } from "../api";
import { StatusDialog } from "../components/StatusDialog";
import { Async, Banner, Card, SectionHeading, StatTile, StatusPill } from "../components/ui";
import { hours, mins, num, pct, statusLabel } from "../format";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";
import type { Item } from "../types";
import { bucketFor, bucketNoun, bucketTick, groupSeries } from "../series";
import { TOOLTIP } from "../charts";
import { Donut } from "../components/Donut";
import { EffortDrilldown } from "../components/EffortDrilldown";
import { RankedBars } from "../components/RankedBars";
import { useState } from "react";

export function MemberDetail({ range }: { range: Range }) {
  const memberId = Number(useParams().id);
  const p = { from: range.from, to: range.to, member_id: memberId };
  const deps = [memberId, range.from, range.to];
  const [moving, setMoving] = useState<Item | null>(null);

  const profile = useApi(() => api.memberProfile(memberId, p), deps);
  const members = useApi(() => api.members({ is_active: undefined }), []);
  const stats = useApi(() => api.byMember(p), deps);
  const adherence = useApi(() => api.adherence(p), deps);
  const cycle = useApi(() => api.cycleTime(p), deps);
  const types = useApi(() => api.byTaskType(p), deps);
  const entries = useApi(() => api.workLog({ ...p, page_size: 100 }), deps);
  const trend = useApi(() => api.trend(p), deps);

  // Same day/week/month rule as everywhere else, so a quarter reads as ~14
  // points rather than 92.
  const bucket = bucketFor(range.from, range.to);
  const trendRows = groupSeries(trend.data ?? [], bucket, ["tasks", "volume", "closed"]);

  const member = (members.data ?? []).find((m) => m.id === memberId);
  const stat = (stats.data ?? [])[0];
  const adhere = (adherence.data ?? [])[0];

  // The profile call is the one gated by "may I see this person" — every
  // other fetch on this page silently falls back to the viewer's own data
  // instead of erroring, so it's this error (not those) that means "blocked",
  // and it's checked before any of that mismatched data can render.
  if (profile.error) {
    return (
      <>
        <SectionHeading title={member?.display_name ?? `Member ${memberId}`} />
        <Banner tone="warn">No access — you can only view your own profile.</Banner>
      </>
    );
  }

  return (
    <>
      <SectionHeading title={member?.display_name ?? `Member ${memberId}`} />

      <Async loading={profile.loading} error={profile.error} data={profile.data}>
        {(pr) => (
          <>
            {/* Who this is and how they're doing, before any number. The
                sentence was already generated below the stats; it belongs at
                the top, where it frames them. */}
            <section className="profile-head card">
              <div className="profile-id">
                <span className="profile-avatar" aria-hidden="true">
                  {(member?.display_name ?? "?").slice(0, 1).toUpperCase()}
                </span>
                <div>
                  <h2 className="profile-name">
                    {member?.display_name ?? `Member ${memberId}`}
                    <span className="pill pill-muted">{member?.role ?? pr.member.role}</span>
                  </h2>
                  <p className="profile-sub">
                    {member?.email ?? "No email on file — can't sign in yet"}
                  </p>
                </div>
              </div>
              <p className="profile-summary">
                {pr.by_pipeline.length ? (
                  <>
                    Mostly <strong>{[...pr.by_pipeline].sort((a, b) =>
                      b.effort_minutes - a.effort_minutes)[0].label}</strong>
                    {" — "}{pct([...pr.by_pipeline].sort((a, b) =>
                      b.effort_minutes - a.effort_minutes)[0].effort_minutes /
                      (pr.totals.effort_minutes || 1))} of their hours
                    {pr.totals.tasks
                      ? `, ${mins(Math.round(pr.totals.effort_minutes / pr.totals.tasks))} per ticket`
                      : ""}
                    .{" "}
                    {pr.by_customer.length
                      ? `Worked for ${pr.by_customer.length} customers.`
                      : "No customer recorded — Jira only captures it on Content Requests."}
                  </>
                ) : (
                  <>Nothing logged in this range.</>
                )}
              </p>
            </section>

            <div className="stat-row stat-row--bare" style={{ marginTop: 12 }}>
              <StatTile
                label="Effort logged"
                value={mins(pr.totals.effort_minutes || null)}
                sub="every stream combined"
                accent="var(--accent-orange)"
              />
              <StatTile label="Tickets" value={num(pr.totals.tasks)} accent="var(--accent-blue)" />
              <StatTile
                label="Share of team effort"
                value={pct(pr.share_of_team.effort)}
                sub={`${pct(pr.share_of_team.tasks)} of tickets`}
                accent="var(--accent-indigo)"
              />
              <StatTile label="Done" value={pct(pr.totals.completion_rate)}
                        sub={`${pr.totals.closed} of ${pr.totals.tasks}`} accent="var(--accent-aqua)" />
              <StatTile label="Customers" value={num(pr.by_customer.length)} />
            </div>


            <SectionHeading title="Where the time went" color="var(--accent-magenta)" />

            {/* The headline hours, opened up — which stream, which work type,
                which customer, and the individual tickets underneath. */}
            <Card title="Effort, accounted for" sub="every logged minute, traceable to a ticket">
              <EffortDrilldown data={pr.effort_breakdown} showPeople={false} />
            </Card>

            <div className="grid cols-2" style={{ marginTop: 12 }}>
              <Card title="By stream" sub="share of their hours">
                <Donut
                  slices={pr.by_pipeline.map((s) => ({
                    key: s.pipeline, label: s.label, value: s.effort_minutes,
                  }))}
                  totalLabel="their effort"
                  format={(n) => mins(n)}
                />
              </Card>
              <Card title="Work areas" sub="hours by type of work">
                {pr.by_task_type.length === 0 ? (
                  <div className="empty">Nothing categorised yet.</div>
                ) : (
                  <RankedBars
                    items={pr.by_task_type.slice(0, 9).map((r) => ({
                      key: r.task_type, label: r.task_type,
                      value: r.effort_minutes, sub: `${r.tasks} tickets`,
                    }))}
                    format={(n) => mins(n)}
                  />
                )}
              </Card>
            </div>

            <div className="grid cols-2" style={{ marginTop: 12 }}>
              <Card title="Customers" sub="Content Requests only — Jira records it nowhere else">
                {pr.by_customer.length === 0 ? (
                  <div className="empty">No customer recorded against their work.</div>
                ) : (
                  <RankedBars
                    items={pr.by_customer.slice(0, 9).map((c) => ({
                      key: c.customer, label: c.customer,
                      value: c.effort_minutes, sub: `${c.tasks} tickets`,
                    }))}
                    format={(n) => mins(n)}
                  />
                )}
              </Card>
              <Card title="Question types" sub="what they build">
                {pr.by_question_type.length === 0 ? (
                  <div className="empty">Nothing tagged.</div>
                ) : (
                  <RankedBars
                    items={pr.by_question_type.map((q) => ({
                      key: q.question_type, label: q.question_type, value: q.tasks,
                    }))}
                  />
                )}
              </Card>
            </div>

            <SectionHeading title="Detail" color="var(--accent-blue)" />
          </>
        )}
      </Async>

      <div className="stat-row">
        <StatTile label="Tasks" value={num(stat?.tasks ?? 0)} accent="var(--accent-blue)" />
        <StatTile label="Items produced" value={num(stat?.volume ?? 0)} accent="var(--accent-indigo)" />
        <StatTile
          label="Effort logged"
          value={mins(stat?.effort_minutes || null)}
          accent="var(--accent-orange)"
        />
        <StatTile label="Completion" value={pct(stat?.completion_rate)} accent="var(--accent-aqua)" />
        <StatTile label="Open" value={num(stat?.open ?? 0)} />
        <StatTile label="Blocked" value={num(stat?.blocked ?? 0)} accent="var(--accent-red)" />
        <StatTile
          label="Median cycle"
          value={hours(cycle.data?.median_hours)}
          sub={`${cycle.data?.closed_tasks ?? 0} closed`}
        />
      </div>

      <Card title="Output over time" sub={`per ${bucketNoun(bucket)}`} >
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
                  stroke="var(--ink-3)"
                  fontSize={11}
                />
                <YAxis
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                  stroke="var(--ink-3)"
                  fontSize={11}
                />
                <Tooltip
                  contentStyle={TOOLTIP}
                  labelFormatter={(d) => bucketTick(String(d), bucket)}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="tasks" name="Tasks" fill="var(--accent-blue)" radius={[3, 3, 0, 0]} maxBarSize={26} />
                <Bar dataKey="volume" name="Items" fill="var(--accent-indigo)" radius={[3, 3, 0, 0]} maxBarSize={26} />
                <Line dataKey="closed" name="Closed" stroke="var(--accent-aqua)" strokeWidth={2} dot={false} type="monotone" />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </Async>
      </Card>

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

        <Card title="What they worked on" sub="by work type, this range">
          <Async loading={types.loading} error={types.error} data={types.data}
                 empty={{ title: "Nothing logged" }}>
            {(rows) => (
              <div className="table-scroll" style={{ border: 0, boxShadow: "none" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Work type</th>
                      <th className="num">Tasks</th>
                      <th className="num">Items</th>
                      <th className="num">Effort</th>
                      <th className="num">Open</th>
                      <th className="num">Done</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.task_type}>
                        <td className="strong">{r.task_type}</td>
                        <td className="num">{r.tasks}</td>
                        <td className="num">{r.volume || "—"}</td>
                        <td className="num">{mins(r.effort_minutes || null)}</td>
                        <td className="num">{r.open + r.in_progress + r.blocked || "—"}</td>
                        <td className="num">{r.closed || "—"}</td>
                      </tr>
                    ))}
                    <tr>
                      <td className="strong">Total</td>
                      <td className="num strong">{rows.reduce((s, r) => s + r.tasks, 0)}</td>
                      <td className="num strong">{rows.reduce((s, r) => s + r.volume, 0)}</td>
                      <td className="num strong">
                        {mins(rows.reduce((s, r) => s + r.effort_minutes, 0) || null)}
                      </td>
                      <td className="num strong">
                        {rows.reduce((s, r) => s + r.open + r.in_progress + r.blocked, 0)}
                      </td>
                      <td className="num strong">{rows.reduce((s, r) => s + r.closed, 0)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </Async>
        </Card>
      </div>

      <SectionHeading title="Every task, in order" color="var(--accent-orange)" />
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
            <div className="table-scroll table-scroll--capped">
              <table className="sticky-col">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Stream</th>
                    <th>Work type</th>
                    <th>Customer</th>
                    <th className="num">Count</th>
                    <th className="num">Effort</th>
                    <th>Status</th>
                    <th>Due</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((r) => (
                    <tr key={r.id}>
                      <td className="mono strong">{r.entry_date}</td>
                      <td>
                        <span className="pill pill-muted">
                          {r.external_issue_type ?? (r.kind === "plan" ? "Plan" : "Update")}
                        </span>
                      </td>
                      <td>{r.task_type}</td>
                      <td className="muted">{r.customer ?? "—"}</td>
                      <td className="num">{num(r.count)}</td>
                      <td className="num">{mins(r.effort_minutes)}</td>
                      <td>
                        {r.kind === "update" && r.plan_item_id === null ? (
                          <StatusPill status={r.status} />
                        ) : (
                          <button
                            className={`pill pill-${r.status} pill-button`}
                            onClick={() => setMoving({ ...r, task_type_id: 0 })}
                            title="Move status"
                          >
                            {statusLabel(r.status)}
                          </button>
                        )}
                      </td>
                      <td className="mono muted">{r.due_at ?? "—"}</td>
                      <td className="cell-notes">{r.notes ?? "—"}</td>
                    </tr>
                  ))}
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
