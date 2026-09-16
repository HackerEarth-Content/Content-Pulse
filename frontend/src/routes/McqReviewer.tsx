import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api";
import { Banner, SectionHeading, Skeleton } from "../components/ui";
import { Donut } from "../components/Donut";
import { shadeFor } from "../charts";
import type { McqDistributionGroup, McqReviewJobDetail, McqReviewJobSummary } from "../types";

const STAGES = [
  { key: "uploaded", label: "Uploaded" },
  { key: "parsing", label: "Parsing workbook" },
  { key: "parsed", label: "Parsed" },
  { key: "reviewing", label: "Reviewing questions" },
] as const;

const ACCEPTED = [".xls", ".xlsx"];
const POLL_MS = 2000;

function isTerminal(status: string) {
  return status === "done" || status === "failed";
}

/** Polls a job until it reaches done/failed. Stops itself on unmount or once
 * terminal — nothing keeps ticking after the screen no longer needs it.
 * `seed` is the summary already in hand from the upload response or the
 * Recent Uploads list, so the stage checklist renders on the very first
 * frame instead of a generic full-page skeleton while the first poll is
 * still in flight. */
function useJobPoll(jobId: number | null, seed?: McqReviewJobSummary | null) {
  const [job, setJob] = useState<McqReviewJobDetail | null>(
    seed ? { ...seed, error: null, result: null, updated_at: seed.created_at } : null
  );
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    if (jobId === null) {
      setJob(null);
      return;
    }
    const id = jobId;
    setJob(seed && seed.id === id ? { ...seed, error: null, result: null, updated_at: seed.created_at } : null);
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick() {
      try {
        const result = await api.mcqReviewJob(id);
        if (cancelled) return;
        setJob(result);
        setError(null);
        if (!isTerminal(result.status)) timer = setTimeout(tick, POLL_MS);
      } catch (e) {
        if (!cancelled) setError(e as ApiError);
      }
    }
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  return { job, error };
}

function RecentJobs({ onPick }: { onPick: (job: McqReviewJobSummary) => void }) {
  const [jobs, setJobs] = useState<McqReviewJobSummary[] | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.myMcqReviewJobs().then(setJobs).catch(() => setJobs([]));
  }, []);

  if (!jobs || jobs.length === 0) return null;

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <button
        className="card-title" style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls="recent-uploads-list"
      >
        Recent uploads ({jobs.length}) {open ? "▾" : "▸"}
      </button>
      {open ? (
        <div id="recent-uploads-list" className="reveal-stagger" style={{ display: "grid", gap: 6, marginTop: 10 }}>
          {jobs.map((j) => (
            <button
              key={j.id}
              className="btn btn-secondary"
              style={{ justifyContent: "space-between", display: "flex" }}
              onClick={() => onPick(j)}
            >
              <span>{j.filename}</span>
              <span className={`pill pill-${j.status === "failed" ? "blocked" : j.status === "done" ? "closed" : "in_progress"}`}>
                {j.status}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function UploadForm({ onUploaded }: { onUploaded: (job: McqReviewJobSummary) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function pick(f: File | null) {
    if (f && !ACCEPTED.some((ext) => f.name.toLowerCase().endsWith(ext))) {
      setError(new ApiError(0, "bad_extension", "Only .xls or .xlsx files are accepted."));
      return;
    }
    setError(null);
    setFile(f);
  }

  function clear() {
    setFile(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function submit() {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const job = await api.uploadMcqReview(file);
      onUploaded(job);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="card">
      <div className="card-title">Upload a bulk MCQ workbook</div>
      <p className="card-sub">Must follow the HackerEarth bulk-upload template exactly — same columns, same order.</p>

      <input
        ref={inputRef} type="file" accept=".xls,.xlsx" hidden
        aria-label="MCQ workbook file"
        onChange={(e) => pick(e.target.files?.[0] ?? null)}
      />

      {file ? (
        <div className="mcq-file-chip" style={{ marginTop: 12 }}>
          <span className="mcq-file-icon" aria-hidden>📄</span>
          <span className="mcq-file-name">{file.name}</span>
          <button
            type="button"
            className="mcq-file-remove"
            aria-label={`Remove ${file.name}`}
            onClick={clear}
          >
            ✕
          </button>
        </div>
      ) : (
        <div
          className="field mcq-dropzone"
          role="button"
          tabIndex={0}
          aria-label="Choose or drop a bulk MCQ workbook file"
          style={{
            marginTop: 12, padding: "28px 16px", textAlign: "center", cursor: "pointer",
            borderStyle: "dashed", borderWidth: 2,
          }}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              inputRef.current?.click();
            }
          }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            pick(e.dataTransfer.files[0] ?? null);
          }}
        >
          <span>Drag a file here, or click to choose one</span>
        </div>
      )}

      {error ? <Banner tone="error">{error.message}</Banner> : null}

      <div className="btn-row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
        <button className="btn btn-primary" disabled={!file || uploading} onClick={submit}>
          {uploading ? "Uploading…" : "Review this set"}
        </button>
      </div>
    </div>
  );
}

function ProgressPanel({ job }: { job: McqReviewJobDetail }) {
  const stageIndex = STAGES.findIndex((s) => s.key === job.status);
  const pct = Math.round(((stageIndex + 1) / STAGES.length) * 100);
  return (
    <div className="card" role="status" aria-live="polite">
      <div className="card-title">{job.filename}</div>
      <div className="mcq-progress-track" aria-hidden>
        <div className="mcq-progress-fill" style={{ transform: `scaleX(${pct / 100})` }} />
      </div>
      <div style={{ display: "grid", gap: 10, marginTop: 14 }}>
        {STAGES.map((s, i) => (
          <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 10, opacity: i <= stageIndex ? 1 : 0.4 }}>
            {i < stageIndex ? (
              <span>✓</span>
            ) : i === stageIndex ? (
              <svg className="spin" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
                   strokeWidth="2.6" strokeLinecap="round" aria-hidden="true">
                <path d="M21 12a9 9 0 11-2.6-6.4M21 3v6h-6" />
              </svg>
            ) : (
              <span className="skeleton" style={{ width: 15, height: 15, borderRadius: "50%", display: "inline-block" }} />
            )}
            <span>{s.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const OPTION_ORDER_KEY = (k: string) => Number(k);

/** One option-count group's answer-choice split, as a donut: each option's
 * observed share as a wedge, coloured by the ordinal ramp (there's no fixed
 * identity to an "Option C" across charts, so a magnitude ramp stays inside
 * the CVD-safe token set instead of inventing a 4th/5th categorical hue).
 * Options that miss the even-split tolerance are called out below by name
 * and delta, since colour alone can't carry "off" once it's already carrying
 * option identity. */
function DistributionChart({ groupKey, group }: { groupKey: string; group: McqDistributionGroup }) {
  const n = groupKey.replace("_option", "");
  const options = Object.keys(group.observed_distribution).sort(
    (a, b) => OPTION_ORDER_KEY(a) - OPTION_ORDER_KEY(b)
  );
  const expected = group.expected_distribution[options[0]] ?? 0;
  const offOptions = options
    .map((opt) => ({ opt, observed: group.observed_distribution[opt], delta: group.observed_distribution[opt] - expected }))
    .filter((o) => Math.abs(o.delta) > 5);

  return (
    <div className="card">
      <div className="card-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>{n}-option questions</span>
        <span className={`pill pill-${group.status === "within_tolerance" ? "closed" : "blocked"}`}>
          {group.status === "within_tolerance" ? "Balanced" : "Skewed"}
        </span>
      </div>
      <p className="card-sub" style={{ marginBottom: 10 }}>
        {group.sample_size} valid question{group.sample_size === 1 ? "" : "s"} · expected {expected}% per option, ±5pt tolerance
      </p>
      <Donut
        slices={options.map((opt, i) => ({
          key: opt,
          label: `Option ${opt}`,
          value: group.observed_distribution[opt],
          colour: shadeFor(i, options.length),
        }))}
        format={(v) => `${Math.round(v)}%`}
        totalLabel="of the set"
        maxSlices={options.length}
      />
      {offOptions.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
          {offOptions.map(({ opt, observed, delta }) => (
            <span key={opt} className="pill pill-blocked">
              Option {opt}: {observed}% ({delta > 0 ? "+" : ""}{delta}pt)
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Insights({ job }: { job: McqReviewJobDetail }) {
  const summary = job.result?.set_summary;
  if (!summary) return null;
  const distGroups = Object.entries(summary.answer_choice_distribution);
  const topIssues = Object.entries(summary.most_frequent_issues).sort((a, b) => b[1].count - a[1].count);

  const complexity = summary.complexity_mismatch;
  const hasComplexity = complexity && complexity.structurally_valid_rows_assessed > 0;

  if (distGroups.length === 0 && topIssues.length === 0 && !hasComplexity) return null;

  return (
    <>
      <SectionHeading title="Answer-choice split & complexity match" color="var(--accent-aqua)" />
      {distGroups.length === 0 && !hasComplexity ? (
        <Banner tone="info">No structurally valid questions to measure a split on.</Banner>
      ) : (
        <div className="grid cols-2 reveal-stagger">
          {distGroups.map(([key, group]) => (
            <DistributionChart key={key} groupKey={key} group={group} />
          ))}
          {hasComplexity ? (
            <div className="card">
              <div className="card-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span>Rows assessed for complexity</span>
                <span className={`pill pill-${complexity.mismatch_pct <= 10 ? "closed" : "blocked"}`}>
                  {complexity.mismatch_pct}% mismatch
                </span>
              </div>
              <p className="card-sub" style={{ marginBottom: 10 }}>
                {complexity.rows_with_mismatch} of {complexity.structurally_valid_rows_assessed} rows tagged at the wrong complexity
              </p>
              <Donut
                slices={[
                  {
                    key: "matched",
                    label: "Matched",
                    value: complexity.structurally_valid_rows_assessed - complexity.rows_with_mismatch,
                    colour: "var(--status-good)",
                  },
                  { key: "mismatched", label: "Mismatched", value: complexity.rows_with_mismatch, colour: "var(--status-critical)" },
                ]}
                totalLabel="rows assessed"
              />
            </div>
          ) : null}
        </div>
      )}

      {topIssues.length > 0 ? (
        <>
          <SectionHeading title="Most frequent issues" color="var(--accent-violet, var(--accent-indigo))" />
          <div className="card">
            <div className="bar-list">
              {topIssues.map(([name, info]) => (
                <div className="bar-row" key={name}>
                  <div>
                    <div className="bar-label">{name.replace(/_/g, " ")}</div>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${info.pct_of_reviewed}%` }} />
                    </div>
                  </div>
                  <div className="bar-value">{info.count}</div>
                </div>
              ))}
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}

function Results({ job }: { job: McqReviewJobDetail }) {
  const result = job.result;
  if (!result) return null;
  const overall = result.set_summary.overall_results;

  return (
    <>
      <div className="grid cols-3">
        <div className="stat"><span className="stat-label">Total questions</span><div className="stat-value">{overall?.total ?? "—"}</div></div>
        <div className="stat"><span className="stat-label">Passed</span><div className="stat-value">{overall?.passed ?? "—"}</div></div>
        <div className="stat"><span className="stat-label">Flagged</span><div className="stat-value">{overall?.failed ?? "—"}</div></div>
      </div>

      <Insights job={job} />

      {result.question_reviews.length === 0 ? (
        <div className="card mcq-clean-state">
          <span className="mcq-clean-icon" aria-hidden>
            <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor"
                 strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 13l4 4L19 7" />
            </svg>
          </span>
          <div>
            <div className="mcq-clean-title">Clean set</div>
            <p className="card-sub" style={{ margin: 0 }}>
              No issues found across {overall?.total} question{overall?.total === 1 ? "" : "s"}.
            </p>
          </div>
        </div>
      ) : (
        <>
          <SectionHeading title="Flagged questions" color="var(--accent-blue)" />
          <div className="reveal-stagger" style={{ display: "grid", gap: 10 }}>
            {result.question_reviews.map((qr) => (
              <div className="card" key={qr.row_number}>
                <div className="card-title">Row {qr.row_number}</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, margin: "6px 0" }}>
                  {Object.entries(qr.checks).map(([name, check]) => (
                    <span key={name} className={`pill pill-${check.status === "fail" ? "blocked" : "in_progress"}`}>
                      {name}: {check.status}
                    </span>
                  ))}
                </div>
                <p className="card-sub">{qr.suggestion}</p>
              </div>
            ))}
          </div>
        </>
      )}

      {result.set_summary.skill_tag_analysis_status === "taxonomy_not_provided" ? (
        <Banner tone="warn">
          Skill-tag coverage wasn't evaluated — the taxonomy is empty.{" "}
          <Link to="/utils/taxonomy">Add tags in Skill Taxonomy</Link>.
        </Banner>
      ) : null}
    </>
  );
}

/** Upload → poll → results, resumable from the URL (job_id) and from the
 * Recent Uploads list — losing the tab doesn't lose the job, since it keeps
 * running server-side regardless. */
export function McqReviewer() {
  const params = useParams<{ jobId?: string }>();
  const navigate = useNavigate();
  const jobId = params.jobId ? Number(params.jobId) : null;
  // Carried across the navigate() from upload/Recent Uploads so the stage
  // checklist has something to show on the very first frame of the new
  // route, instead of a blank generic skeleton while the first poll lands.
  const [seed, setSeed] = useState<McqReviewJobSummary | null>(null);
  const { job, error: pollError } = useJobPoll(jobId, seed);
  // One level of back-navigation at a time: a job detail (reached from the
  // upload form or Recent Uploads) steps back to this same page's base view,
  // not straight past it to the Utils landing page.
  const backTo = jobId === null ? "/utils" : "/utils/mcq-reviewer";

  function open(j: McqReviewJobSummary) {
    setSeed(j);
    navigate(`/utils/mcq-reviewer/${j.id}`);
  }

  return (
    <>
      <div className="util-page-head">
        <Link className="btn btn-secondary" to={backTo}>← Back</Link>
        <span className="util-page-title">MCQ Reviewer</span>
      </div>
      <p className="tab-blurb">Upload a bulk MCQ workbook for an AI-reviewed quality report.</p>

      {jobId === null ? (
        <>
          <UploadForm onUploaded={open} />
          <RecentJobs onPick={open} />
        </>
      ) : pollError ? (
        <Banner tone="error">{pollError.message}</Banner>
      ) : !job ? (
        <Skeleton rows={4} height={44} />
      ) : job.status === "failed" ? (
        <>
          <Banner tone="error">{job.error ?? "The review failed."}</Banner>
          <div className="btn-row" style={{ marginTop: 12 }}>
            <button className="btn btn-primary" onClick={() => navigate("/utils/mcq-reviewer")}>
              Try another file
            </button>
          </div>
        </>
      ) : job.status === "done" ? (
        <Results job={job} />
      ) : (
        <ProgressPanel job={job} />
      )}
    </>
  );
}
