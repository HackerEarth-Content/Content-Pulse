import type { CSSProperties, ReactNode } from "react";
import { useState } from "react";
import {
  Bar, BarChart, Cell, PolarAngleAxis, PolarGrid, Radar, RadarChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api";
import { AXIS, TOOLTIP, shadeFor } from "../charts";
import { Donut } from "../components/Donut";
import { RedashSyncDialog } from "../components/RedashSyncDialog";
import { Async, Card, SectionHeading, StatTile } from "../components/ui";
import { num, pct, relativeTime } from "../format";
import { useApi } from "../hooks/useApi";
import { useCountUp } from "../hooks/useCountUp";
import { useRedashSync } from "../hooks/useRedashSync";
import type { ContentHealthType, CoverageAction } from "../types";

const DETAIL_TABS = ["By topic", "Top companies"] as const;
type DetailTab = (typeof DETAIL_TABS)[number];

const ACTION_ORDER: CoverageAction[] = ["add", "top_up", "prune", "balanced"];
const VERDICT_CHIP_LABEL: Record<CoverageAction, string> = {
  add: "add", top_up: "top up", prune: "prune", balanced: "balanced",
};
// Mirrors the thresholds in backend/services/content_health.py's _action()
// exactly (AttQ_Under=30, AttQ_Tight=15, Dead_Prune=0.6) — if those ever
// change, this text has to change with them.
const VERDICT_EXPLAIN: Record<CoverageAction, string> = {
  add: "Att/Q ≥ 30 — heavily used relative to how many questions exist. Add more questions to this topic.",
  top_up: "Att/Q ≥ 15 (below 30) — getting tight. A few more questions would help.",
  prune: "Att/Q < 15 and Dead % ≥ 60% — mostly unused. Consider pruning the dead questions.",
  balanced: "Att/Q < 15 and Dead % < 60% — healthy supply relative to demand. No action needed.",
};
const COLUMN_EXPLAIN = {
  topic: "Grouped by the [prefix] in the question title, or its first tag if there's no prefix.",
  questions: "Number of questions in this topic/group.",
  dead: "Share of this topic's questions that got zero attempts this month.",
  attempts: "Total candidate attempts across this topic's questions this month.",
  attq: "Attempts ÷ Questions — attempt density per question. This is what the verdict is based on.",
  health: "Average of each question's Health score, as set on HackerEarth.",
  emh: "Question count by difficulty: Easy / Medium / Hard.",
  verdict: "ADD if Att/Q ≥ 30 · top up if Att/Q ≥ 15 · prune if Dead % ≥ 60% · else balanced.",
} as const;

// Content health data only goes back to when the library started being
// tracked this way — May 2026 (see scripts/backfill_content_health.py's
// DEFAULT_FROM). Listing exactly that range, newest first, rather than a
// generic "last month / this month" toggle, is what makes May reachable at
// all — it otherwise falls further out of range every month that passes.
const FIRST_TRACKED_MONTH = new Date(2026, 4, 1);

interface MonthOption {
  ym: string;
  from: string;
  to: string;
  label: string;
}

function monthOption(d: Date): MonthOption {
  const start = new Date(d.getFullYear(), d.getMonth(), 1);
  const end = new Date(start.getFullYear(), start.getMonth() + 1, 0);
  const iso = (x: Date) => x.toLocaleDateString("en-CA");
  return {
    ym: `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}`,
    from: iso(start),
    to: iso(end),
    label: start.toLocaleDateString(undefined, { month: "long", year: "numeric" }),
  };
}

function trackedMonths(): MonthOption[] {
  const months: MonthOption[] = [];
  const now = new Date();
  let d = new Date(now.getFullYear(), now.getMonth(), 1);
  while (d >= FIRST_TRACKED_MONTH) {
    months.push(monthOption(d));
    d = new Date(d.getFullYear(), d.getMonth() - 1, 1);
  }
  return months; // most recent first
}

/** A stat tile whose headline number tweens in on change, instead of just
 *  appearing — off under prefers-reduced-motion (see useCountUp). */
function AnimatedStat({ label, value, sub }: { label: string; value: number | null; sub?: string }) {
  const shown = useCountUp(value);
  return <StatTile label={label} value={shown === null ? "—" : shown.toLocaleString()} sub={sub} />;
}

/** A card that can turn around: an (i) button swaps the chart for a plain
 *  explanation of what it's showing and exactly how it's computed, instead
 *  of leaving that as something to guess at or ask about. */
function InfoCard({
  title, sub, accent, explain, children,
}: { title: string; sub?: string; accent: string; explain: ReactNode; children: ReactNode }) {
  const [showInfo, setShowInfo] = useState(false);
  return (
    <Card
      title={title}
      sub={sub}
      action={
        <button
          className="info-toggle"
          style={{ "--card-accent": accent } as CSSProperties}
          onClick={() => setShowInfo((s) => !s)}
          aria-pressed={showInfo}
          aria-label={showInfo ? "Back to chart" : "How is this calculated?"}
          title={showInfo ? "Back to chart" : "How is this calculated?"}
        >
          {showInfo ? "✕" : "?"}
        </button>
      }
    >
      <div key={showInfo ? "info" : "chart"} className="info-swap">
        {showInfo ? <div className="info-explain">{explain}</div> : children}
      </div>
    </Card>
  );
}

/** Three real, independently-meaningful ratios for one question type — never
 *  fabricated to fill a shape. A single series only: recharts overlaying all
 *  8 problem types on one radar would need 8 mutually distinguishable hues,
 *  and this app's own colour system (charts.ts) proves only 3 survive a CVD
 *  check — so it's one subject's shape, switchable, not eight overlapping
 *  ones. */
function radarData(t: ContentHealthType, all: ContentHealthType[]) {
  const maxAttempted = Math.max(1, ...all.map((x) => x.candidates_attempted ?? 0));
  const pct100 = (n: number) => Math.round(n * 100);
  return [
    { axis: "Test coverage", value: t.tests_published ? pct100((t.tests_with_qt ?? 0) / t.tests_published) : 0 },
    { axis: "Library adoption", value: t.tests_with_qt ? pct100((t.tests_with_library ?? 0) / t.tests_with_qt) : 0 },
    { axis: "Engagement", value: pct100((t.candidates_attempted ?? 0) / maxAttempted) },
  ];
}

function HealthRadar({ type, all }: { type: ContentHealthType; all: ContentHealthType[] }) {
  return (
    <ResponsiveContainer width="100%" height={340}>
      <RadarChart data={radarData(type, all)} outerRadius="78%">
        <PolarGrid stroke="var(--line)" />
        <PolarAngleAxis dataKey="axis" tick={{ fill: AXIS.stroke, fontSize: 12 }} />
        <Radar
          dataKey="value"
          stroke="var(--accent-indigo)"
          fill="var(--accent-indigo)"
          fillOpacity={0.45}
          strokeWidth={2.5}
          isAnimationActive
        />
        <Tooltip formatter={(v: number) => `${v}%`} contentStyle={TOOLTIP} />
      </RadarChart>
    </ResponsiveContainer>
  );
}

/** A bounded 0–5 rating as a ring, not a bar — the shape says "out of a
 *  fixed scale" the way a bar reads as "share of an open-ended total".
 *  Plain conic-gradient, no chart library: it's one native property. */
function RatingGauge({ value, sub }: { value: number | null; sub?: string }) {
  const shown = useCountUp(value === null ? null : Math.round(value * 20));
  const pctValue = shown ?? 0;
  return (
    <div className="gauge-card">
      <div className="gauge-ring" style={{ "--gauge-pct": pctValue } as CSSProperties}>
        <div className="gauge-hole">
          <span className="gauge-value">{value === null ? "—" : value.toFixed(2)}</span>
          <span className="gauge-unit">/ 5</span>
        </div>
      </div>
      <span className="stat-label">Avg candidate rating</span>
      {sub ? <span className="gauge-sub">{sub}</span> : null}
    </div>
  );
}

/** An actual axis-and-bar chart for the top companies, not a ranked list —
 *  horizontal bars because company names read better left-aligned than
 *  stacked under a vertical axis. Rank-coloured, same convention as the
 *  donuts and the question-type grid. */
function CompaniesBarChart({
  companies, valueLabel,
}: { companies: { company: string; value: number | null }[]; valueLabel: string }) {
  const data = companies.map((c) => ({ name: c.company, value: c.value ?? 0 }));
  return (
    <ResponsiveContainer width="100%" height={Math.max(220, data.length * 34)}>
      <BarChart data={data} layout="vertical" margin={{ left: 4, right: 20, top: 4, bottom: 4 }}>
        <XAxis
          type="number" tick={{ fill: AXIS.stroke, fontSize: AXIS.fontSize }}
          axisLine={{ stroke: "var(--line)" }} tickLine={false}
        />
        <YAxis
          type="category" dataKey="name" width={150}
          tick={{ fill: AXIS.stroke, fontSize: AXIS.fontSize }}
          axisLine={{ stroke: "var(--line)" }} tickLine={false}
        />
        <Tooltip
          formatter={(v: number) => [v.toLocaleString(), valueLabel]}
          contentStyle={TOOLTIP} cursor={{ fill: "var(--surface-2)" }}
        />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive>
          {data.map((_, i) => <Cell key={i} fill={shadeFor(i, data.length)} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** A tile per question type, ranked by candidates attempted — replaces a
 *  thin list of bars with something closer to a small stat card each, and
 *  lives inside a fixed-height scroll container so the page doesn't grow one
 *  row per type as more months and types accumulate data. */
function QuestionTypeGrid({
  types, selected, onSelect,
}: { types: ContentHealthType[]; selected: string | null; onSelect: (key: string) => void }) {
  const ranked = [...types].sort((a, b) => (b.candidates_attempted ?? 0) - (a.candidates_attempted ?? 0));
  const max = Math.max(1, ...ranked.map((t) => t.candidates_attempted ?? 0));
  return (
    <div className="qt-scroll">
      <div className="qt-grid reveal-stagger">
        {ranked.map((t, i) => {
          const accent = shadeFor(i, ranked.length);
          const share = Math.round(((t.candidates_attempted ?? 0) / max) * 100);
          return (
            <button
              key={t.problem_type}
              className={`qt-tile${selected === t.problem_type ? " active" : ""}`}
              style={{ "--qt-accent": accent } as CSSProperties}
              onClick={() => onSelect(t.problem_type)}
              aria-pressed={selected === t.problem_type}
            >
              <div className="qt-tile-top">
                <span className="qt-tile-rank">#{i + 1}</span>
                <span className="qt-tile-name">{t.problem_type}</span>
              </div>
              <span className="qt-tile-value mono">{num(t.candidates_attempted ?? 0)}</span>
              <span className="qt-tile-sub">candidates attempted</span>
              <div className="qt-tile-bar"><div className="qt-tile-fill" style={{ width: `${share}%` }} /></div>
              <span className="qt-tile-sub2">{num(t.tests_with_qt)} tests contain this type</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function ContentHealth() {
  const months = trackedMonths();
  const [ym, setYm] = useState(months[0].ym);
  const [selected, setSelected] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("By topic");
  const [verdictFilter, setVerdictFilter] = useState<CoverageAction | null>(null);
  const [syncDialogOpen, setSyncDialogOpen] = useState(false);
  const { from, to, label } = months.find((m) => m.ym === ym) ?? months[0];
  const sync = useRedashSync();

  const selectMonth = (next: string) => {
    if (next === ym) return;
    setYm(next);
    // A drilldown selection from the old month rarely applies to the new
    // one — clear it rather than show possibly-mismatched coverage data
    // under a type name that happens to still exist.
    setSelected(null);
    setVerdictFilter(null);
  };

  const overview = useApi(() => api.contentHealthOverview({ from, to }), [from, to]);
  const coverage = useApi(
    () => (selected ? api.contentHealthCoverage(selected, { from, to }) : Promise.resolve(null)),
    [selected, from, to]
  );
  const companies = useApi(
    () => (selected ? api.contentHealthCompanies(selected, { from, to }) : Promise.resolve(null)),
    [selected, from, to]
  );

  return (
    <>
      <SectionHeading
        title="Content Health"
        color="var(--accent-aqua)"
        action={
          <span className="sync">
            <span className="sync-age" aria-live="polite">
              {sync.syncing
                ? "Syncing from Redash…"
                : sync.lastError
                  ? `Sync failed — ${sync.lastError.slice(0, 60)}`
                  : sync.lastSynced
                    ? `Redash synced ${relativeTime(sync.lastSynced)}`
                    : "Not synced yet"}
            </span>
            <button
              className="btn btn-secondary"
              disabled={sync.syncing}
              title="Pull the latest candidate usage and coverage from Redash"
              onClick={() => setSyncDialogOpen(true)}
            >
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                   strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"
                   className={sync.syncing ? "spin" : undefined} aria-hidden="true"
                   style={{ marginRight: 6, verticalAlign: -2 }}>
                <path d="M21 12a9 9 0 11-2.6-6.4M21 3v6h-6" />
              </svg>
              {sync.syncing ? "Syncing…" : "Sync from Redash"}
            </button>
          </span>
        }
      />

      {syncDialogOpen ? (
        <RedashSyncDialog
          lastSynced={sync.lastSynced}
          onClose={() => setSyncDialogOpen(false)}
          onConfirm={() => {
            sync.refresh(from, to);
            setSyncDialogOpen(false);
          }}
        />
      ) : null}

      <div className="month-strip" role="tablist" aria-label="Month">
        {months.map((m) => (
          <button
            key={m.ym}
            role="tab"
            aria-selected={ym === m.ym}
            className={`month-pill${ym === m.ym ? " active" : ""}`}
            onClick={() => selectMonth(m.ym)}
          >
            {m.label}
          </button>
        ))}
      </div>
      <p className="tab-blurb">
        Candidate usage, feedback and topic coverage for the HE question library — {label}.
      </p>

      <Async loading={overview.loading} error={overview.error} data={overview.data}
             empty={{ title: "No content health data for this month yet", hint: "Sync from Redash above to pull it." }}>
        {(data) => {
          // tests_published is the same platform-wide total on every row —
          // summing it across types would multiply one constant by 8, not
          // add anything real. Read it once instead.
          const totalPublished = data.problem_types[0]?.tests_published ?? null;
          const totalAttempted = data.problem_types.reduce((s, t) => s + (t.candidates_attempted ?? 0), 0);
          const radarSubject =
            data.problem_types.find((t) => t.problem_type === selected) ??
            [...data.problem_types].sort((a, b) => (b.candidates_attempted ?? 0) - (a.candidates_attempted ?? 0))[0];
          const pick = (key: string) => {
            setSelected(key === selected ? null : key);
            setDetailTab("By topic");
            setVerdictFilter(null);
          };
          return (
            <div className="month-fade" key={ym}>
              <div className="stat-row reveal-stagger">
                <AnimatedStat label="Tests published" value={totalPublished} sub="platform-wide total for the month" />
                <AnimatedStat label="Candidates attempted" value={totalAttempted} sub="summed across all question types" />
              </div>

              {data.problem_types.length ? (
                <div className="bento-grid">
                  <InfoCard
                    title="Candidates attempted"
                    sub="Every question type's share — nothing folded into “Other”"
                    accent="var(--accent-aqua)"
                    explain={
                      <>
                        <p>Each slice is one question type's share of <strong>{num(totalAttempted)}</strong> total
                          candidate attempts this month — <code>candidates_attempted for that type ÷ total across all
                          8 types</code>. Colour here is rank order (darkest = most attempted), not identity — the
                          label on each slice and in the legend carries that instead, the same convention the
                          ranked list below uses.</p>
                        <p>Source: Redash queries 5156 / 5549 (per-question attempt counts, summed per type),
                          re-run fresh for {label}.</p>
                      </>
                    }
                  >
                    <Donut
                      slices={[...data.problem_types]
                        .filter((t) => (t.candidates_attempted ?? 0) > 0)
                        .sort((a, b) => (b.candidates_attempted ?? 0) - (a.candidates_attempted ?? 0))
                        .map((t, i, arr) => ({
                          key: t.problem_type, label: t.problem_type, value: t.candidates_attempted ?? 0,
                          colour: shadeFor(i, arr.length),
                        }))}
                      total={totalAttempted}
                      totalLabel="attempted"
                      maxSlices={data.problem_types.length}
                      onSelect={pick}
                      selected={selected}
                    />
                  </InfoCard>

                  <InfoCard
                    title="Health profile"
                    sub={selected ? `${radarSubject.problem_type} — click a type below to switch` : `${radarSubject.problem_type} — busiest this month, by candidates attempted`}
                    accent="var(--accent-indigo)"
                    explain={
                      <>
                        <p>Three independent ratios for <strong>{radarSubject.problem_type}</strong>, each a real
                          share of something — nothing here is invented to fill out the shape:</p>
                        <ul>
                          <li><strong>Test coverage</strong> — tests containing this type ÷ all tests published this
                            month ({num(radarSubject.tests_with_qt)} / {num(radarSubject.tests_published)}).</li>
                          <li><strong>Library adoption</strong> — of those tests, the % that also draw on HE-library
                            questions ({num(radarSubject.tests_with_library)} / {num(radarSubject.tests_with_qt)}).</li>
                          <li><strong>Engagement</strong> — this type's candidates attempted against the busiest
                            type this month ({num(radarSubject.candidates_attempted)} attempts).</li>
                        </ul>
                        <p>A dent toward the centre on any axis is the actual gap — not a comparison you have to do
                          in your head against seven other numbers.</p>
                      </>
                    }
                  >
                    <HealthRadar type={radarSubject} all={data.problem_types} />
                  </InfoCard>

                  <InfoCard
                    title="Candidate feedback"
                    sub="Platform-wide — not split by question type"
                    accent="var(--accent-orange)"
                    explain={
                      <>
                        <p>The mean of every rated test slug's <code>avg_candidate_rating</code> this month, on a
                          0–5 scale — {data.feedback ? `${num(data.feedback.slugs_with_rating)} of ${num(data.feedback.total_slugs)} test slugs had a rating` : "no data yet"}.
                          Zero-value ratings (no one rated it) are excluded rather than counted as a 0.</p>
                        <p>Source: Redash query 5215. This one genuinely is global — the query itself isn't
                          parameterised by problem type, so it can't be split per type the way the donut and radar
                          are.</p>
                      </>
                    }
                  >
                    <RatingGauge
                      value={data.feedback?.avg_rating ?? null}
                      sub={data.feedback ? `${num(data.feedback.slugs_with_rating)} of ${num(data.feedback.total_slugs)} test slugs rated` : undefined}
                    />
                  </InfoCard>
                </div>
              ) : null}

              <Card title="By question type" sub="Candidates attempted, ranked — click a tile to drill in">
                {data.problem_types.length ? (
                  <QuestionTypeGrid types={data.problem_types} selected={selected} onSelect={pick} />
                ) : (
                  <p className="muted">No problem types synced yet.</p>
                )}
              </Card>

              {selected ? (
                <div className="expand-panel" key={selected}>
                  {(() => {
                    const t = data.problem_types.find((p) => p.problem_type === selected);
                    return t ? (
                      <div className="stat-row stat-row--bare">
                        <AnimatedStat label="Tests with this QT" value={t.tests_with_qt} />
                        <AnimatedStat label="Tests with HE library Qs" value={t.tests_with_library} />
                        <AnimatedStat label="Library questions used" value={t.library_questions_used} />
                        <AnimatedStat label="Candidates attempted" value={t.candidates_attempted} />
                      </div>
                    ) : null;
                  })()}

                  <div className="nav drilldown-tabs" role="tablist" aria-label="Break coverage down by">
                    {DETAIL_TABS.map((tab) => (
                      <button
                        key={tab}
                        role="tab"
                        aria-selected={detailTab === tab}
                        className={`nav-link${detailTab === tab ? " active" : ""}`}
                        onClick={() => setDetailTab(tab)}
                      >
                        {tab}
                      </button>
                    ))}
                  </div>

                  {detailTab === "By topic" ? (
                    <Async loading={coverage.loading} error={coverage.error} data={coverage.data}
                           empty={{ title: "No per-question data for this type", hint: "The 5156/5549 Redash query returned nothing for this period." }}>
                      {(cov) => {
                        const rows = verdictFilter ? cov.topics.filter((g) => g.action === verdictFilter) : cov.topics;
                        return (
                          <>
                            <div className="drilldown-caveats" style={{ justifyContent: "flex-start", marginBottom: 10 }}>
                              {ACTION_ORDER.map((a) => (
                                <button
                                  key={a}
                                  type="button"
                                  className={`pill pill-${a} pill-button`}
                                  aria-pressed={verdictFilter === a}
                                  title={VERDICT_EXPLAIN[a]}
                                  onClick={() => setVerdictFilter(verdictFilter === a ? null : a)}
                                >
                                  {cov.verdicts[a] ?? 0} {VERDICT_CHIP_LABEL[a]}
                                </button>
                              ))}
                              {verdictFilter ? (
                                <button type="button" className="pill pill-muted" onClick={() => setVerdictFilter(null)}>
                                  clear filter ✕
                                </button>
                              ) : null}
                            </div>
                            <div className="table-scroll table-scroll--capped">
                              <table className="table">
                                <thead>
                                  <tr>
                                    <th title={COLUMN_EXPLAIN.topic}>Topic</th>
                                    <th className="num" title={COLUMN_EXPLAIN.questions}>Questions</th>
                                    <th className="num" title={COLUMN_EXPLAIN.dead}>Dead %</th>
                                    <th className="num" title={COLUMN_EXPLAIN.attempts}>Attempts</th>
                                    <th className="num" title={COLUMN_EXPLAIN.attq}>Att/Q</th>
                                    <th className="num" title={COLUMN_EXPLAIN.health}>Avg health</th>
                                    <th title={COLUMN_EXPLAIN.emh}>E/M/H</th>
                                    <th title={COLUMN_EXPLAIN.verdict}>Verdict</th>
                                  </tr>
                                </thead>
                                <tbody className="reveal-stagger">
                                  {rows.map((g) => (
                                    <tr key={g.topic}>
                                      <td>{g.topic}</td>
                                      <td className="num mono">{num(g.questions)}</td>
                                      <td className="num mono">{pct(g.dead_pct / 100)}</td>
                                      <td className="num mono">{num(g.attempts)}</td>
                                      <td className="num mono">{g.att_per_q}</td>
                                      <td className="num mono">{g.avg_health ?? "—"}</td>
                                      <td className="mono">{g.difficulty.easy}/{g.difficulty.medium}/{g.difficulty.hard}</td>
                                      <td><span className={`pill pill-${g.action}`} title={VERDICT_EXPLAIN[g.action]}>{g.action_label}</span></td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                            {verdictFilter && !rows.length ? (
                              <p className="muted">No topics with this verdict.</p>
                            ) : null}
                          </>
                        );
                      }}
                    </Async>
                  ) : (
                    <Async loading={companies.loading} error={companies.error} data={companies.data}
                           empty={{ title: "No top-company data for this type" }}>
                      {(comp) =>
                        comp.companies.length ? (
                          <>
                            <p className="hint">
                              Top {comp.companies.length} companies for {selected} by {comp.value_label ?? "candidate volume"}.
                            </p>
                            <CompaniesBarChart companies={comp.companies} valueLabel={comp.value_label ?? "candidates"} />
                          </>
                        ) : (
                          <p className="muted">No data.</p>
                        )
                      }
                    </Async>
                  )}
                </div>
              ) : null}
            </div>
          );
        }}
      </Async>
    </>
  );
}
