import { useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api";
import { AXIS, CATEGORICAL, MUTED, TOOLTIP } from "../charts";
import { Donut } from "../components/Donut";
import { Async, Card, SectionHeading, StatTile } from "../components/ui";
import { num, relativeTime } from "../format";
import { useApi } from "../hooks/useApi";
import { useContentIssueSync } from "../hooks/useContentIssueSync";

type Mode = "weekly" | "monthly";

// The "Content Issue" request type has been tracked in Jira since August
// 2026 — listing exactly that range, newest first, is what keeps every past
// month reachable as more of them accumulate (see ContentHealth.tsx's
// identical FIRST_TRACKED_MONTH reasoning).
const FIRST_TRACKED = new Date(2026, 7, 1);

interface PeriodOption {
  key: string;
  from: string;
  to: string;
  label: string;
}

const iso = (d: Date) => d.toLocaleDateString("en-CA");

function monthOption(d: Date): PeriodOption {
  const start = new Date(d.getFullYear(), d.getMonth(), 1);
  const end = new Date(start.getFullYear(), start.getMonth() + 1, 0);
  return {
    key: `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}`,
    from: iso(start),
    to: iso(end),
    label: start.toLocaleDateString(undefined, { month: "long", year: "numeric" }),
  };
}

function trackedMonths(): PeriodOption[] {
  const months: PeriodOption[] = [];
  const now = new Date();
  let d = new Date(now.getFullYear(), now.getMonth(), 1);
  while (d >= FIRST_TRACKED) {
    months.push(monthOption(d));
    d = new Date(d.getFullYear(), d.getMonth() - 1, 1);
  }
  return months;
}

/** Monday of the calendar week containing `d` — a fixed week, not a rolling
 *  "last 7 days", so "previous week" means something stable to click back to. */
function mondayOf(d: Date): Date {
  const day = d.getDay();
  const diff = (day === 0 ? -6 : 1) - day;
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + diff);
}

function weekOption(monday: Date): PeriodOption {
  const end = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 6);
  const fmt = (x: Date) => x.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return { key: iso(monday), from: iso(monday), to: iso(end), label: `${fmt(monday)} – ${fmt(end)}` };
}

function trackedWeeks(): PeriodOption[] {
  const weeks: PeriodOption[] = [];
  const firstMonday = mondayOf(FIRST_TRACKED);
  let d = mondayOf(new Date());
  while (d >= firstMonday) {
    weeks.push(weekOption(d));
    d = new Date(d.getFullYear(), d.getMonth(), d.getDate() - 7);
  }
  return weeks;
}

function dayOf(dateIso: string): string {
  return `${new Date(`${dateIso}T00:00:00`).getDate()}`;
}

export function ContentIssueAnalysis() {
  const [mode, setMode] = useState<Mode>("weekly");
  const weeks = useMemo(trackedWeeks, []);
  const months = useMemo(trackedMonths, []);
  const [weekKey, setWeekKey] = useState(weeks[0]?.key);
  const [monthKey, setMonthKey] = useState(months[0]?.key);
  const sync = useContentIssueSync();

  const options = mode === "weekly" ? weeks : months;
  const selectedKey = mode === "weekly" ? weekKey : monthKey;
  const period = options.find((o) => o.key === selectedKey) ?? options[0];
  const { from, to, label } = period ?? { from: "", to: "", label: "" };

  const overview = useApi(() => api.contentIssuesOverview({ from, to }), [from, to]);

  const cumulative = useMemo(() => {
    if (!overview.data) return [];
    let running = 0;
    return overview.data.daily.map((d) => {
      running += d.valid;
      return { date: dayOf(d.date), cumulative: running };
    });
  }, [overview.data]);

  return (
    <>
      <SectionHeading
        title="Content Issue Analysis"
        color="var(--accent-orange)"
        action={
          <span className="sync">
            <span className="sync-age" aria-live="polite">
              {sync.syncing
                ? "Syncing from Jira…"
                : sync.lastError
                  ? `Sync failed — ${sync.lastError.slice(0, 60)}`
                  : sync.lastSynced
                    ? `Synced ${relativeTime(sync.lastSynced)}`
                    : "Not synced yet"}
            </span>
            <button className="btn btn-secondary" disabled={sync.syncing} onClick={sync.refresh}>
              {sync.syncing ? "Syncing…" : "Sync from Jira"}
            </button>
          </span>
        }
      />

      <div className="period-group" role="radiogroup" aria-label="Weekly or monthly" style={{ marginBottom: 10, width: "fit-content" }}>
        {(["weekly", "monthly"] as const).map((m) => (
          <button
            key={m}
            role="radio"
            aria-checked={mode === m}
            className="period-btn"
            onClick={() => setMode(m)}
          >
            {m === "weekly" ? "Weekly" : "Monthly"}
          </button>
        ))}
      </div>

      <div className="month-strip" role="tablist" aria-label={mode === "weekly" ? "Week" : "Month"}>
        {options.map((o) => (
          <button
            key={o.key}
            role="tab"
            aria-selected={selectedKey === o.key}
            className={`month-pill${selectedKey === o.key ? " active" : ""}`}
            onClick={() => (mode === "weekly" ? setWeekKey(o.key) : setMonthKey(o.key))}
          >
            {o.label}
          </button>
        ))}
      </div>
      <p className="tab-blurb">
        {mode === "weekly"
          ? `Content issues reported the week of ${label}.`
          : `Content issues reported in ${label} — the flow across the month, not just the total.`}
      </p>

      <Async
        loading={overview.loading}
        error={overview.error}
        data={overview.data}
        empty={{ title: "No content issues reported in this range yet", hint: "Sync from Jira above to pull it." }}
      >
        {(data) => (
          <div className="month-fade" key={selectedKey}>
            <div className="stat-row reveal-stagger">
              <StatTile label="Total reported" value={num(data.total)} />
              <StatTile label="Valid" value={num(data.valid_count)} accent="var(--accent-aqua)" />
              <StatTile label="Invalid" value={num(data.invalid_count)} accent="var(--accent-indigo)" />
              <StatTile label="Customer-flagged" value={num(data.customer_count)} accent="var(--accent-orange)" />
              <StatTile label="Platform issue" value={num(data.platform_count)} accent="var(--accent-blue)" />
              {/* Always shown, even at 0 — hiding this tile when it's zero is
                  exactly what made "6 reported, 3 valid + 1 invalid" look like
                  a bug instead of 2 not-yet-triaged issues. */}
              <StatTile label="Pending triage" value={num(data.unknown_count)} sub="no status set yet" />
            </div>
            <p className="hint">
              Valid + Invalid + Customer-flagged + Platform issue + Pending triage always adds up to Total reported.
            </p>

            <div className="bento-grid">
              <Card title="Status breakdown" sub="Valid / invalid / customer-flagged / platform issue, this range">
                <Donut
                  slices={[
                    { key: "valid", label: "Valid", value: data.valid_count, colour: CATEGORICAL[0] },
                    { key: "invalid", label: "Invalid", value: data.invalid_count, colour: CATEGORICAL[1] },
                    { key: "customer", label: "Customer", value: data.customer_count, colour: CATEGORICAL[2] },
                    { key: "platform_issue", label: "Platform issue", value: data.platform_count, colour: "var(--accent-blue)" },
                    { key: "unknown", label: "Pending triage", value: data.unknown_count, colour: MUTED },
                  ]}
                  total={data.total}
                  totalLabel="reported"
                  maxSlices={5}
                />
              </Card>

              <Card title="Impact" sub="Summed across valid issues only">
                <div className="stat-row stat-row--bare">
                  <StatTile label="Tests impacted" value={num(data.impact.tests_impacted)} />
                  <StatTile label="Candidates impacted" value={num(data.impact.candidates_impacted)} />
                  <StatTile label="Customers impacted" value={num(data.impact.customers_impacted)} />
                </div>
              </Card>
            </div>

            <Card title="Valid issues by setter" sub={label}>
              {data.setters.length ? (
                <div className="setter-list">
                  {data.setters.map((s) => (
                    <div className="setter-row" key={`${s.setter}-${s.setter_last_modified}`}>
                      <div className="setter-row-main">
                        <span className="setter-name">{s.setter}</span>
                        <span className="setter-modified">Last modified by {s.setter_last_modified}</span>
                        <div className="setter-issue-links">
                          {s.issues.map((issue) => (
                            <a key={issue.issue_key} className="tag" href={issue.url} target="_blank" rel="noreferrer">
                              {issue.issue_key}
                            </a>
                          ))}
                        </div>
                      </div>
                      <span className="pill pill-muted mono">{s.count}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">No valid issues in this range.</p>
              )}
            </Card>

            {mode === "monthly" ? (
              <>
                <Card title="Issues per day" sub="Stacked by status — is volume or the invalid rate trending?">
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={data.daily.map((d) => ({ ...d, day: dayOf(d.date) }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
                      <XAxis dataKey="day" tick={{ fill: AXIS.stroke, fontSize: AXIS.fontSize }} axisLine={{ stroke: "var(--line)" }} tickLine={false} />
                      <YAxis tick={{ fill: AXIS.stroke, fontSize: AXIS.fontSize }} axisLine={{ stroke: "var(--line)" }} tickLine={false} allowDecimals={false} />
                      <Tooltip contentStyle={TOOLTIP} cursor={{ fill: "var(--surface-2)" }} />
                      <Bar dataKey="valid" stackId="s" fill={CATEGORICAL[0]} name="Valid" />
                      <Bar dataKey="invalid" stackId="s" fill={CATEGORICAL[1]} name="Invalid" />
                      <Bar dataKey="customer" stackId="s" fill={CATEGORICAL[2]} name="Customer" />
                      <Bar dataKey="platform_issue" stackId="s" fill="var(--accent-blue)" name="Platform issue" />
                      <Bar dataKey="unknown" stackId="s" fill={MUTED} name="Pending triage" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </Card>

                <Card title="Cumulative valid issues" sub="Running total across the month">
                  <ResponsiveContainer width="100%" height={220}>
                    <LineChart data={cumulative}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
                      <XAxis dataKey="date" tick={{ fill: AXIS.stroke, fontSize: AXIS.fontSize }} axisLine={{ stroke: "var(--line)" }} tickLine={false} />
                      <YAxis tick={{ fill: AXIS.stroke, fontSize: AXIS.fontSize }} axisLine={{ stroke: "var(--line)" }} tickLine={false} allowDecimals={false} />
                      <Tooltip contentStyle={TOOLTIP} />
                      <Line type="monotone" dataKey="cumulative" stroke={CATEGORICAL[0]} strokeWidth={2.5} dot={false} isAnimationActive />
                    </LineChart>
                  </ResponsiveContainer>
                </Card>
              </>
            ) : null}
          </div>
        )}
      </Async>
    </>
  );
}
