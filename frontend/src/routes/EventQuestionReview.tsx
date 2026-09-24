import { useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api";
import { Banner, Skeleton } from "../components/ui";
import { useApi } from "../hooks/useApi";
import type {
  CurrentUser,
  EqrHistory,
  EqrImportJob,
  EqrImportSummary,
  EqrQuestionRow,
  EqrVerdict,
  Member,
} from "../types";

type Me = CurrentUser["member"];

const STATUS_LABEL: Record<EqrVerdict, string> = {
  no_issue_found: "No issue found",
  fixed: "Fixed",
  removed: "Removed from library",
};
const STATUS_PILL: Record<EqrVerdict, string> = {
  no_issue_found: "closed",
  fixed: "in_progress",
  removed: "blocked",
};
const STALE_DAYS = 90;

/** Inline single-stroke SVGs, matching Shell.tsx/Utils.tsx's own icon
 * convention — an icon set would be another dependency for a handful of
 * glyphs; raw emoji (the previous version of this file) render inconsistently
 * across platforms and don't match that convention. */
function Icon({ d, size = 14 }: { d: string; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" width={size} height={size}>
      <path d={d} />
    </svg>
  );
}
function ClockIcon({ size = 14 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" width={size} height={size}>
      <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" />
    </svg>
  );
}
const PATH = {
  chevronRight: "M9 6l6 6-6 6",
  chevronDown: "M6 9l6 6 6-6",
  chevronUp: "M6 15l6-6 6 6",
  close: "M6 6l12 12M18 6L6 18",
  download: "M12 3v13m0 0l-4-4m4 4l4-4M5 19h14",
  upload: "M12 16V3m0 0l4 4m-4-4L8 7M5 19h14",
};

/** Same two URL shapes the backend's `extract_slug` recognizes — done here
 * too so the slug preview updates on every keystroke without a round trip. */
function extractSlug(text: string): string | null {
  const raw = text.trim();
  const patterns = [/\/recruiter\/([a-z0-9-]+)\/?/i, /\/challenges\/test\/([a-z0-9-]+)\/?/i];
  for (const p of patterns) {
    const m = raw.match(p);
    if (m) return m[1];
  }
  return /^[a-z0-9-]+$/i.test(raw) ? raw : null;
}

function staleMonths(iso: string): number {
  return Math.round((Date.now() - new Date(iso).getTime()) / (1000 * 60 * 60 * 24 * 30));
}
function isStale(row: EqrQuestionRow): boolean {
  return row.l1_status === "done" && !!row.last_reviewed_at
    && Date.now() - new Date(row.last_reviewed_at).getTime() >= STALE_DAYS * 86400000;
}
function isMine(row: EqrQuestionRow, me: Me): boolean {
  if (!me) return false;
  return (row.l1_status !== "done" && row.l1_assignee?.id === me.id)
    || (["pending", "in_progress"].includes(row.l2_status) && row.l2_assignee?.id === me.id);
}

/** Closes an open popover on a click anywhere outside it — the one thing a
 * hand-rolled dropdown doesn't get for free the way a native <select> does. */
function useClickOutside(ref: RefObject<HTMLElement | null>, onOutside: () => void, active: boolean) {
  useEffect(() => {
    if (!active) return;
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onOutside();
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [active, onOutside]);
}

function UrlForm({ isAdmin }: { isAdmin: boolean }) {
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [slugFallback, setSlugFallback] = useState("");
  const [showFallback, setShowFallback] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const slug = extractSlug(url);

  function go() {
    const resolved = (showFallback && slugFallback.trim()) || slug;
    if (!resolved) return;
    navigate(`/utils/event-review/${resolved}`);
  }

  return (
    <>
      <div className="card">
        <div className="card-title">Event URL</div>
        <p className="card-sub" style={{ marginBottom: 10 }}>
          e.g. a recruiter question-bank link, or a public challenge link.
        </p>
        <input
          className="field"
          placeholder="https://www.hackerearth.com/challenges/test/…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <p className="card-sub" style={{ marginTop: 8 }}>
          {url && (slug ? <>Resolved event slug: <code>{slug}</code></> : "Couldn't parse a slug from this URL — paste it directly below.")}
        </p>
        <button className="btn btn-secondary btn-sm" type="button" onClick={() => setShowFallback((s) => !s)}>
          Can't parse it? Paste the slug directly
        </button>
        {showFallback && (
          <input
            className="field" style={{ marginTop: 8 }}
            placeholder="event-slug-goes-here"
            value={slugFallback}
            onChange={(e) => setSlugFallback(e.target.value)}
          />
        )}
        <div className="btn-row" style={{ justifyContent: "flex-end" }}>
          <button className="btn btn-primary" disabled={!slug && !slugFallback.trim()} onClick={go}>
            Fetch questions
          </button>
        </div>
      </div>

      {isAdmin && (
        <div className="card" style={{ marginTop: 14 }}>
          <div className="card-title">Import past review data</div>
          <p className="card-sub" style={{ marginBottom: 10 }}>
            Admin-only. Upload a workbook in the reference format to backfill already-reviewed questions —
            never overwrites a question that already has real review work in the app.
          </p>
          <div className="btn-row" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn-secondary" type="button" onClick={() => setImportOpen(true)}>
              <Icon d={PATH.upload} size={12} /> Import workbook
            </button>
          </div>
          {importOpen && <ImportDialog onClose={() => setImportOpen(false)} onImported={() => {}} />}
        </div>
      )}
    </>
  );
}

/** A generic native-<dialog> confirm — used instead of `window.confirm()`,
 * which breaks out of the app's own theming (no dark mode, no styling) for
 * the one destructive action (reassigning a completed L2 review) that used
 * to reach for it. */
function ConfirmDialog({
  title, body, confirmLabel, onConfirm, onCancel,
}: { title: string; body: string; confirmLabel: string; onConfirm: () => void; onCancel: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);

  return (
    <dialog ref={ref} className="dialog" onClose={onCancel} onCancel={onCancel}>
      <div className="dialog-head">
        <div className="card-title">{title}</div>
        <button className="section-action" onClick={() => ref.current?.close()} aria-label="Close"><Icon d={PATH.close} size={12} /></button>
      </div>
      <p className="card-sub">{body}</p>
      <div className="btn-row" style={{ justifyContent: "flex-end" }}>
        <button className="btn btn-secondary" onClick={() => ref.current?.close()}>Cancel</button>
        <button className="btn btn-danger" onClick={() => { ref.current?.close(); onConfirm(); }}>{confirmLabel}</button>
      </div>
    </dialog>
  );
}

/** The warning is deliberately distinct from the plain "no default" note —
 * "removed" is the most consequential of the three verdicts (logs a
 * library-cleanup request, per EVENT_QUESTION_REVIEW.md), so it gets its
 * own visible callout instead of reading as just another option. */
function RemovedWarning() {
  return (
    <Banner tone="warn">
      This only logs a removal request here — it does not remove the question from the real library. That stays a manual, separate step.
    </Banner>
  );
}

function VerdictForm({
  onSubmit,
}: {
  onSubmit: (status: EqrVerdict, note: string) => Promise<void>;
}) {
  const [status, setStatus] = useState<EqrVerdict | "">("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const needsNote = status === "fixed" || status === "removed";

  async function submit() {
    if (!status) { setError("Choose a verdict — no default is assumed."); return; }
    if (needsNote && !note.trim()) {
      setError(status === "fixed" ? "Fixed needs a summary." : "Removed needs a reason.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      await onSubmit(status, note.trim());
    } catch (e) {
      setError((e as ApiError).message);
      setSaving(false);
    }
  }

  return (
    <div className="verdict-form">
      <select className="field" value={status} onChange={(e) => setStatus(e.target.value as EqrVerdict)}>
        <option value="">Choose a verdict…</option>
        <option value="no_issue_found">No issue found</option>
        <option value="fixed">Fixed</option>
        <option value="removed">Removed from library</option>
      </select>
      {status === "removed" && <RemovedWarning />}
      {needsNote && (
        <textarea
          className="field"
          placeholder="Summary of the fix, or the reason for removal — required."
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      )}
      {error && <p className="card-sub" style={{ color: "var(--status-critical)" }}>{error}</p>}
      <div className="btn-row" style={{ marginTop: 0, justifyContent: "flex-end" }}>
        <button className="btn btn-primary btn-sm" disabled={saving} onClick={submit}>
          {saving ? "Submitting…" : "Submit review"}
        </button>
      </div>
    </div>
  );
}

function DetailPanel({
  row, me, isAdmin, members, currentSlug, onChanged, onOpenHistory,
}: {
  row: EqrQuestionRow;
  me: Me;
  isAdmin: boolean;
  members: Member[];
  currentSlug: string;
  onChanged: (rows: EqrQuestionRow[]) => void;
  onOpenHistory: () => void;
}) {
  const [l2Pick, setL2Pick] = useState("");
  const [l2Comment, setL2Comment] = useState(row.l2_comments || "");
  const [l2Error, setL2Error] = useState<string | null>(null);
  const [l2Busy, setL2Busy] = useState(false);
  const [confirmReassign, setConfirmReassign] = useState(false);
  const [editing, setEditing] = useState(false);
  const editableHere = row.last_reviewed_slug === currentSlug;
  const stale = isStale(row);
  const canAssignL2 = !!row.l1_assignee;

  async function requestL2() {
    if (!l2Pick) return;
    setL2Error(null);
    setL2Busy(true);
    try {
      const updated = await api.eventReviewAssign({
        setter_template_ids: [row.setter_template_id], member_id: Number(l2Pick), level: "l2",
      });
      onChanged(updated);
    } catch (e) {
      setL2Error((e as ApiError).message);
    } finally {
      setL2Busy(false);
    }
  }
  async function startL2() {
    setL2Error(null);
    setL2Busy(true);
    try {
      const updated = await api.eventReviewClaim({ setter_template_id: row.setter_template_id, level: "l2" });
      onChanged([updated]);
    } catch (e) {
      setL2Error((e as ApiError).message);
    } finally {
      setL2Busy(false);
    }
  }
  async function finishL2() {
    if (!l2Comment.trim()) { setL2Error("L2 sign-off needs a comment before it can be marked done."); return; }
    setL2Error(null);
    setL2Busy(true);
    try {
      const updated = await api.eventReviewL2Submit({ setter_template_id: row.setter_template_id, comment: l2Comment.trim() });
      onChanged([updated]);
    } catch (e) {
      setL2Error((e as ApiError).message);
    } finally {
      setL2Busy(false);
    }
  }
  async function doReassign() {
    if (!l2Pick) return;
    setL2Error(null);
    setL2Busy(true);
    try {
      const updated = await api.eventReviewReassignL2({ setter_template_id: row.setter_template_id, member_id: Number(l2Pick) });
      onChanged([updated]);
    } catch (e) {
      setL2Error((e as ApiError).message);
    } finally {
      setL2Busy(false);
    }
  }
  function reassignL2() {
    if (!l2Pick) return;
    if (row.l2_status === "done") { setConfirmReassign(true); return; }
    doReassign();
  }

  return (
    <div className="eqr-detail">
      <p className="card-sub">
        Problem ID {row.problem_id} · {row.question_type} · {row.tags.join(", ") || "no tags"}
      </p>
      {row.description && <p className="card-sub">{row.description}</p>}

      {row.resurfaced_removed && (
        <Banner tone="error">
          Marked <strong>removed</strong> on {row.last_reviewed_at ? new Date(row.last_reviewed_at).toLocaleDateString() : "—"}, but
          still present in this event's live library pull — library-side removal may not have happened yet.
          This app only logs the request.
        </Banner>
      )}
      {stale && (
        <Banner tone="warn">
          Reviewed {row.last_reviewed_at ? staleMonths(row.last_reviewed_at) : "?"} months ago — GTG. Re-review is only recommended if
          major platform changes or changes to this question type have shipped since.
        </Banner>
      )}

      <div className="eqr-detail-grid">
        <div className="eqr-slot">
          <div className="eqr-slot-label">L1 review</div>
          {row.l1_status === "in_progress" && (
            <VerdictForm
              onSubmit={async (status, note) => {
                const updated = await api.eventReviewSubmit({
                  event_slug: currentSlug,
                  setter_template_ids: [row.setter_template_id],
                  status, note: note || undefined,
                });
                onChanged(updated);
              }}
            />
          )}
          {row.l1_status === "done" && (
            editableHere ? (
              editing ? (
                <VerdictForm
                  onSubmit={async (status, note) => {
                    const updated = await api.eventReviewSubmit({
                      event_slug: currentSlug,
                      setter_template_ids: [row.setter_template_id],
                      status, note: note || undefined,
                    });
                    setEditing(false);
                    onChanged(updated);
                  }}
                />
              ) : (
                <button className="section-action" onClick={() => setEditing(true)}>Edit review</button>
              )
            ) : (
              <p className="card-sub" style={{ fontStyle: "italic" }}>
                Reviewed under a different event ({row.last_reviewed_slug}) — not editable from here.
              </p>
            )
          )}
        </div>

        <div className="eqr-slot">
          <div className="eqr-slot-label">L2 review</div>
          {row.l2_status === "not_requested" && (
            canAssignL2 ? (
              <div className="eqr-inline-row">
                <select className="field" style={{ maxWidth: 170 }} value={l2Pick} onChange={(e) => setL2Pick(e.target.value)}>
                  <option value="">Pick a reviewer…</option>
                  {members.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}
                </select>
                <button className="btn btn-secondary btn-sm" disabled={!l2Pick || l2Busy} onClick={requestL2}>
                  {l2Busy ? "Requesting…" : "Request L2 review"}
                </button>
              </div>
            ) : (
              <p className="card-sub" style={{ fontStyle: "italic" }}>Assign an L1 reviewer first — L2 needs someone to hand off from.</p>
            )
          )}
          {row.l2_status === "pending" && (
            <button className="btn btn-secondary btn-sm" disabled={l2Busy} onClick={startL2}>
              {l2Busy ? "Starting…" : row.l2_assignee?.id === me?.id ? "Start review" : `Start review (as ${row.l2_assignee?.display_name})`}
            </button>
          )}
          {row.l2_status === "in_progress" && (
            <>
              <textarea className="field" placeholder="L2 comments — required to mark done." value={l2Comment}
                        onChange={(e) => setL2Comment(e.target.value)} />
              <div className="btn-row" style={{ marginTop: 6 }}>
                <button className="btn btn-primary btn-sm" disabled={l2Busy} onClick={finishL2}>
                  {l2Busy ? "Saving…" : "Mark L2 review done"}
                </button>
              </div>
            </>
          )}
          {row.l2_status === "done" && (
            <>
              {row.l2_comments && <p className="card-sub">{row.l2_comments}</p>}
              <div className="eqr-inline-row">
                <select className="field" style={{ maxWidth: 150 }} value={l2Pick} onChange={(e) => setL2Pick(e.target.value)}>
                  <option value="">Reassign to…</option>
                  {members.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}
                </select>
                <button className="btn btn-secondary btn-sm" disabled={!l2Pick || l2Busy} onClick={reassignL2}>Reassign L2</button>
              </div>
            </>
          )}
          {l2Error && <p className="card-sub" style={{ color: "var(--status-critical)" }}>{l2Error}</p>}
        </div>
      </div>

      {isAdmin && row.l1_status === "done" && (
        <button className="section-action" onClick={onOpenHistory}>Full history</button>
      )}

      {confirmReassign && (
        <ConfirmDialog
          title="Reassign L2 review?"
          body={`${row.l2_assignee?.display_name} already marked this L2 review done. Reassigning discards their comments and resets it to pending.`}
          confirmLabel="Reassign"
          onCancel={() => setConfirmReassign(false)}
          onConfirm={() => { setConfirmReassign(false); doReassign(); }}
        />
      )}
    </div>
  );
}

function HistoryDialog({ history, onClose }: { history: EqrHistory; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);

  return (
    <dialog ref={ref} className="dialog eqr-history-dialog" onClose={onClose} onCancel={onClose}>
      <div className="dialog-head">
        <div>
          <div className="card-title">Review history</div>
          <div className="card-sub">Setter Template ID {history.setter_template_id}</div>
        </div>
        <button className="section-action" onClick={() => ref.current?.close()} aria-label="Close"><Icon d={PATH.close} size={15} /></button>
      </div>
      <div className="eqr-timeline">
        {history.entries.map((h, i) => (
          <div className="eqr-tl-item" key={i}>
            <div className="eqr-tl-meta">
              {new Date(h.at).toLocaleString()} · {h.level.toUpperCase()} · {h.by} · event <code>{h.event_slug}</code>
            </div>
            <div className="eqr-tl-body">
              {h.verdict && <span className={`pill pill-${STATUS_PILL[h.verdict]}`}>{STATUS_LABEL[h.verdict]}</span>} {h.note}
            </div>
          </div>
        ))}
        {history.entries.length === 0 && <p className="card-sub">No history yet.</p>}
      </div>
      <div className="btn-row" style={{ justifyContent: "flex-end" }}>
        <button className="btn btn-secondary" onClick={() => ref.current?.close()}>Close</button>
      </div>
    </dialog>
  );
}

const EXTRA_COLUMNS: { key: keyof EqrQuestionRow; label: string }[] = [
  { key: "score", label: "Score" },
  { key: "tags", label: "Tags" },
  { key: "created_by", label: "Created by" },
  { key: "added_by", label: "Added by" },
  { key: "library_type", label: "Library type" },
  { key: "workspace", label: "Workspace" },
  { key: "section", label: "Section" },
  { key: "content_created_at", label: "Created at" },
];

const DEFAULT_FILTERS = { search: "", qt: "", level: "", mineOnly: false, staleOnly: false, stage: "all" as const };

function ResultsGrid({ slug, me }: { slug: string; me: Me }) {
  const review = useApi(() => api.eventReview(slug), [slug]);
  const membersState = useApi(() => api.members(), []);
  const members = membersState.data || [];
  const isAdmin = me?.role === "admin";

  // Local copy, seeded once from the fetch and patched in place from each
  // mutation's own response — an assign/claim/submit already returns the
  // updated row(s), so re-fetching the whole event (a live Redash call) just
  // to reflect one change would be slow and pointless.
  const [rows, setRows] = useState<EqrQuestionRow[]>([]);
  useEffect(() => {
    if (review.data) setRows(review.data.rows);
  }, [review.data]);

  function patchRows(updated: EqrQuestionRow[]) {
    setRows((prev) => prev.map((r) => updated.find((u) => u.setter_template_id === r.setter_template_id) ?? r));
  }

  const [search, setSearch] = useState(DEFAULT_FILTERS.search);
  const [qt, setQt] = useState(DEFAULT_FILTERS.qt);
  const [level, setLevel] = useState(DEFAULT_FILTERS.level);
  const [sortKey, setSortKey] = useState<"question_type" | "level" | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  // "all" | "needs" | "done" | "recent" — driven by clicking the stat tiles
  // above instead of a separate segmented control, so there's one filter
  // surface instead of two that could disagree.
  const [stage, setStage] = useState<"all" | "needs" | "done" | "recent">(DEFAULT_FILTERS.stage);
  const [mineOnly, setMineOnly] = useState(DEFAULT_FILTERS.mineOnly);
  const [staleOnly, setStaleOnly] = useState(DEFAULT_FILTERS.staleOnly);
  const [visibleCols, setVisibleCols] = useState<Set<string>>(new Set());
  const [colsOpen, setColsOpen] = useState(false);
  const colsMenuRef = useRef<HTMLDivElement>(null);
  useClickOutside(colsMenuRef, () => setColsOpen(false), colsOpen);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkL1, setBulkL1] = useState("");
  const [bulkL2, setBulkL2] = useState("");
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkVerdictOpen, setBulkVerdictOpen] = useState(false);
  const [history, setHistory] = useState<EqrHistory | null>(null);

  async function openHistory(setterTemplateId: number) {
    setHistory(await api.eventReviewHistory(setterTemplateId));
  }

  function clearFilters() {
    setSearch(DEFAULT_FILTERS.search);
    setQt(DEFAULT_FILTERS.qt);
    setLevel(DEFAULT_FILTERS.level);
    setMineOnly(DEFAULT_FILTERS.mineOnly);
    setStaleOnly(DEFAULT_FILTERS.staleOnly);
    setStage(DEFAULT_FILTERS.stage);
  }

  const questionTypes = useMemo(() => [...new Set(rows.map((r) => r.question_type))], [rows]);
  const levels = useMemo(() => [...new Set(rows.map((r) => r.level))], [rows]);

  // Derived from the live local rows, not the one-time fetch summary — so
  // the headline numbers move the instant a row does, same as the table.
  const needsReviewCount = useMemo(() => rows.filter((r) => r.l1_status !== "done").length, [rows]);
  const reviewedCount = rows.length - needsReviewCount;
  const recentCutoff = Date.now() - 7 * 86400000;
  const recentlyReviewed = useMemo(
    () => rows.filter((r) => r.last_reviewed_at && new Date(r.last_reviewed_at).getTime() >= recentCutoff),
    [rows, recentCutoff]
  );
  const recentIds = useMemo(() => new Set(recentlyReviewed.map((r) => r.setter_template_id)), [recentlyReviewed]);
  const recentNames = [...new Set(recentlyReviewed.map((r) => r.l1_assignee?.display_name).filter(Boolean))];

  const selectedRows = useMemo(() => rows.filter((r) => selected.has(r.setter_template_id)), [rows, selected]);
  const selectedMissingL1 = selectedRows.some((r) => !r.l1_assignee);

  function toggleStage(next: "needs" | "done" | "recent") {
    setStage((s) => (s === next ? "all" : next));
  }

  const filtered = useMemo(() => {
    let list = rows.filter((r) => {
      if (qt && r.question_type !== qt) return false;
      if (level && r.level !== level) return false;
      if (search) {
        const s = search.toLowerCase();
        const matchesId = String(r.setter_template_id).includes(s);
        if (!matchesId && !r.title.toLowerCase().includes(s) && !r.tags.some((t) => t.toLowerCase().includes(s))) return false;
      }
      return true;
    });
    if (mineOnly) list = list.filter((r) => isMine(r, me));
    if (staleOnly) list = list.filter(isStale);
    if (stage === "needs") list = list.filter((r) => r.l1_status !== "done");
    if (stage === "done") list = list.filter((r) => r.l1_status === "done");
    if (stage === "recent") list = list.filter((r) => recentIds.has(r.setter_template_id));
    if (sortKey) {
      list = [...list].sort((a, b) => {
        const cmp = a[sortKey].localeCompare(b[sortKey]);
        return sortDir === "asc" ? cmp : -cmp;
      });
    }
    return list;
  }, [rows, qt, level, search, mineOnly, staleOnly, stage, recentIds, sortKey, sortDir, me]);

  const filtersActive = !!(search || qt || level || mineOnly || staleOnly || stage !== "all");

  function toggleSort(key: "question_type" | "level") {
    if (sortKey !== key) { setSortKey(key); setSortDir("asc"); }
    else if (sortDir === "asc") setSortDir("desc");
    else { setSortKey(null); setSortDir("asc"); }
  }

  function toggleExpand(id: number) {
    setExpanded((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }
  function toggleSelect(id: number, on: boolean) {
    setSelected((s) => { const n = new Set(s); on ? n.add(id) : n.delete(id); return n; });
  }
  function toggleSelectAll(on: boolean) {
    setSelected(on ? new Set(filtered.map((r) => r.setter_template_id)) : new Set());
  }
  function toggleCol(key: string) {
    setVisibleCols((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; });
  }

  async function claimRow(row: EqrQuestionRow, level: "l1" | "l2"): Promise<void> {
    const updated = await api.eventReviewClaim({ setter_template_id: row.setter_template_id, level });
    patchRows([updated]);
  }
  async function bulkAssign(level: "l1" | "l2") {
    const memberId = Number(level === "l1" ? bulkL1 : bulkL2);
    if (!memberId || selected.size === 0) return;
    setBulkError(null);
    if (level === "l2" && selectedMissingL1) {
      setBulkError("Every selected question needs an L1 reviewer before L2 can be assigned.");
      return;
    }
    try {
      const updated = await api.eventReviewAssign({ setter_template_ids: [...selected], member_id: memberId, level });
      patchRows(updated);
      setSelected(new Set());
      setBulkL1(""); setBulkL2("");
    } catch (e) {
      setBulkError((e as ApiError).message);
    }
  }

  if (review.error) return <Banner tone="error">{review.error.message}</Banner>;
  if (review.loading) return <Skeleton rows={4} height={44} />;

  return (
    <>
      <p className="tab-blurb">
        Event: <strong style={{ color: "var(--ink)" }}>{slug}</strong> · {rows.length} library question{rows.length === 1 ? "" : "s"} found
      </p>

      {membersState.error && (
        <Banner tone="error">Couldn't load the members list ({membersState.error.message}) — reviewer pickers will be empty until this loads.</Banner>
      )}

      {rows.length === 0 ? (
        <Banner tone="info">No library questions found for this event.</Banner>
      ) : (
        <>
          <div className="grid cols-4">
            <button
              className="stat" aria-pressed={stage === "all"}
              onClick={() => setStage("all")}
              title="Show every question"
            >
              <span className="stat-label">Total questions</span><div className="stat-value">{rows.length}</div>
            </button>
            <button
              className={`stat eqr-tile-critical${stage === "needs" ? " eqr-tile-active" : ""}`}
              aria-pressed={stage === "needs"}
              onClick={() => toggleStage("needs")}
              title="Filter to questions that still need review"
            >
              <span className="stat-label">Needs review <Icon d={PATH.chevronDown} size={9} /></span>
              <div className="stat-value">{needsReviewCount}</div>
            </button>
            <button
              className={`stat eqr-tile-good${stage === "done" ? " eqr-tile-active" : ""}`}
              aria-pressed={stage === "done"}
              onClick={() => toggleStage("done")}
              title="Filter to already-reviewed questions"
            >
              <span className="stat-label">Reviewed <Icon d={PATH.chevronDown} size={9} /></span>
              <div className="stat-value">{reviewedCount}</div>
            </button>
            <button
              className={`stat${stage === "recent" ? " eqr-tile-active" : ""}`}
              aria-pressed={stage === "recent"}
              onClick={() => toggleStage("recent")}
              title="Filter to questions validated in the last 7 days"
            >
              <span className="stat-label">Validated (7d) <Icon d={PATH.chevronDown} size={9} /></span>
              <div className="stat-value">{recentlyReviewed.length}</div>
              <div className="stat-sub">{recentNames.length ? `by ${recentNames.join(", ")}` : "—"}</div>
            </button>
          </div>

          <div className="eqr-toolbar reveal-stagger">
            <input className="field" style={{ maxWidth: 220 }} placeholder="Search title, tag, or setter ID…" value={search} onChange={(e) => setSearch(e.target.value)} />
            <button className="chip" aria-pressed={mineOnly} onClick={() => setMineOnly((v) => !v)}>My queue</button>
            <button className="chip" aria-pressed={staleOnly} onClick={() => setStaleOnly((v) => !v)}>Stale (3mo+)</button>
            <div style={{ position: "relative" }} ref={colsMenuRef}>
              <button className="chip" onClick={() => setColsOpen((v) => !v)}>
                Columns <Icon d={PATH.chevronDown} size={10} />
              </button>
              {colsOpen && (
                <div className="eqr-columns-menu">
                  {EXTRA_COLUMNS.map((c) => (
                    <label key={String(c.key)}>
                      <input type="checkbox" checked={visibleCols.has(c.key as string)} onChange={() => toggleCol(c.key as string)} />
                      {c.label}
                    </label>
                  ))}
                </div>
              )}
            </div>
            <button className="btn btn-secondary btn-sm" style={{ marginLeft: "auto" }} onClick={() => api.exportEventReview(slug)}>
              <Icon d={PATH.download} size={12} /> Export (.xlsx)
            </button>
          </div>

          {isAdmin && selected.size > 0 && (
            <div>
              <div className="eqr-bulk-bar">
                <span style={{ fontWeight: 600 }}>{selected.size} question{selected.size === 1 ? "" : "s"} selected</span>
                <div className="eqr-bulk-actions">
                  <select className="field" style={{ maxWidth: 150 }} value={bulkL1} onChange={(e) => setBulkL1(e.target.value)}>
                    <option value="">Assign L1 to…</option>
                    {members.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}
                  </select>
                  <button className="btn btn-secondary btn-sm" disabled={!bulkL1} onClick={() => bulkAssign("l1")}>Assign L1</button>
                  <select
                    className="field" style={{ maxWidth: 150 }} value={bulkL2}
                    disabled={selectedMissingL1}
                    title={selectedMissingL1 ? "Every selected question needs an L1 reviewer first." : undefined}
                    onChange={(e) => setBulkL2(e.target.value)}
                  >
                    <option value="">Assign L2 to…</option>
                    {members.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}
                  </select>
                  <button
                    className="btn btn-secondary btn-sm" disabled={!bulkL2 || selectedMissingL1}
                    title={selectedMissingL1 ? "Every selected question needs an L1 reviewer first." : undefined}
                    onClick={() => bulkAssign("l2")}
                  >
                    Assign L2
                  </button>
                  {/* Grouped in their own flex item so wrapping at narrower
                      widths can't split them apart — Close always stays
                      immediately right of Set verdict. */}
                  <div className="eqr-inline-row" style={{ gap: 7, flexWrap: "nowrap" }}>
                    <button className="btn btn-secondary btn-sm" onClick={() => setBulkVerdictOpen(true)}>Set verdict for selected</button>
                    <button className="btn btn-secondary btn-sm" onClick={() => setSelected(new Set())}>Close</button>
                  </div>
                </div>
              </div>
              {bulkError && <p className="card-sub" style={{ color: "var(--status-critical)", margin: "6px 0 0" }}>{bulkError}</p>}
            </div>
          )}

          <div className="table-scroll table-scroll--capped">
            <table className="eqr-grid">
              <thead>
                <tr>
                  {isAdmin && (
                    <th className="eqr-sticky1">
                      <input type="checkbox" checked={filtered.length > 0 && filtered.every((r) => selected.has(r.setter_template_id))}
                             onChange={(e) => toggleSelectAll(e.target.checked)} />
                    </th>
                  )}
                  <th className={isAdmin ? "eqr-sticky2" : "eqr-sticky1"} />
                  <th className={isAdmin ? "eqr-mono" : "eqr-sticky2 eqr-mono"}>Setter ID</th>
                  <th>Title</th>
                  <SortFilterHeader
                    label="QT" sortActive={sortKey === "question_type"} sortDir={sortDir}
                    onSort={() => toggleSort("question_type")}
                    options={questionTypes} value={qt} onChange={setQt}
                  />
                  <SortFilterHeader
                    label="Difficulty" sortActive={sortKey === "level"} sortDir={sortDir}
                    onSort={() => toggleSort("level")}
                    options={levels} value={level} onChange={setLevel}
                  />
                  <th>L1 assignee</th>
                  <th className="eqr-center">L1 status</th>
                  <th>L2 assignee</th>
                  <th className="eqr-center">L2 status</th>
                  <th className="eqr-center">Last verdict</th>
                  <th className="eqr-mono">Last reviewed</th>
                  {EXTRA_COLUMNS.filter((c) => visibleCols.has(c.key as string)).map((c) => <th key={String(c.key)}>{c.label}</th>)}
                  {isAdmin && <th className="eqr-center">History</th>}
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={20} style={{ padding: 24, textAlign: "center", color: "var(--ink-3)" }}>
                      No rows match the current filters.
                      {filtersActive && (
                        <>
                          {" "}
                          <button className="section-action" onClick={clearFilters}>Clear filters</button>
                        </>
                      )}
                    </td>
                  </tr>
                )}
                {filtered.map((row) => (
                  <GridRow
                    key={row.setter_template_id}
                    row={row} me={me} isAdmin={isAdmin} members={members} slug={slug}
                    selected={selected.has(row.setter_template_id)}
                    expanded={expanded.has(row.setter_template_id)}
                    visibleCols={visibleCols}
                    onToggleSelect={(on) => toggleSelect(row.setter_template_id, on)}
                    onToggleExpand={() => toggleExpand(row.setter_template_id)}
                    onClaim={(lvl) => claimRow(row, lvl)}
                    onChanged={patchRows}
                    onOpenHistory={() => openHistory(row.setter_template_id)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <p className="card-sub" style={{ marginTop: 6 }}>
            {isAdmin
              ? "As admin: select rows via the checkbox column to bulk-assign L1, bulk-assign L2 (once L1 is assigned), or set a shared verdict for all of them at once."
              : "Bulk selection and assignment are admin-only — use the row's expand arrow to review one question at a time."}
          </p>

          {bulkVerdictOpen && (
            <BulkVerdictModal
              count={selected.size}
              onCancel={() => setBulkVerdictOpen(false)}
              onSubmit={async (status, note) => {
                const updated = await api.eventReviewSubmit({ event_slug: slug, setter_template_ids: [...selected], status, note: note || undefined });
                patchRows(updated);
                setBulkVerdictOpen(false);
                setSelected(new Set());
              }}
            />
          )}

          {history && <HistoryDialog history={history} onClose={() => setHistory(null)} />}
        </>
      )}
    </>
  );
}

const IMPORT_POLL_MS = 1500;
function isImportPending(status: EqrImportJob["status"]): boolean {
  return status === "uploaded" || status === "validating" || status === "importing";
}

/** Polls an import job until it lands on a state a human needs to act on or
 * read (ready_for_review / done / error) — same self-scheduling shape as
 * McqReviewer's job poll, so a transient poll failure retries instead of
 * silently going stale. */
function useImportJobPoll(job: EqrImportJob | null, setJob: (j: EqrImportJob) => void) {
  useEffect(() => {
    if (!job || !isImportPending(job.status)) return;
    let cancelled = false;
    const id = job.id;
    const timer = setTimeout(async function tick() {
      try {
        const updated = await api.eventReviewImportJob(id);
        if (cancelled) return;
        setJob(updated);
      } catch {
        // transient — the effect below re-arms on the next render regardless
      }
    }, IMPORT_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [job, setJob]);
}

function ImportSummaryView({ summary }: { summary: EqrImportSummary }) {
  const [warningsOpen, setWarningsOpen] = useState(false);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="eqr-inline-row">
        <span className="pill pill-closed">{summary.total_questions} question{summary.total_questions === 1 ? "" : "s"}</span>
        <span className="pill pill-in_progress">
          {summary.total_reviews} review{summary.total_reviews === 1 ? "" : "s"} {summary.dry_run ? "to write" : "written"}
        </span>
        {summary.total_conflicts > 0 && (
          <span className="pill pill-blocked">{summary.total_conflicts} conflict{summary.total_conflicts === 1 ? "" : "s"} skipped</span>
        )}
        {summary.warnings.length > 0 && <span className="pill pill-muted">{summary.warnings.length} warning{summary.warnings.length === 1 ? "" : "s"}</span>}
      </div>

      <table className="eqr-grid" style={{ width: "100%" }}>
        <thead>
          <tr>
            <th>Sheet / event slug</th>
            <th className="eqr-center">Questions</th>
            <th className="eqr-center">Reviews</th>
            <th className="eqr-center">Conflicts</th>
            <th>Missing columns</th>
          </tr>
        </thead>
        <tbody>
          {summary.sheets.map((s) => (
            <tr key={s.slug}>
              <td className="eqr-mono">{s.slug}</td>
              <td className="eqr-center">{s.questions}</td>
              <td className="eqr-center">{s.reviews}</td>
              <td className="eqr-center">{s.conflicts || "—"}</td>
              <td className="eqr-secondary">{s.missing_columns.join(", ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {summary.conflicts.length > 0 && (
        <Banner tone="warn">
          {summary.conflicts.length} question{summary.conflicts.length === 1 ? "" : "s"} already {summary.conflicts.length === 1 ? "has" : "have"} real
          review work in the app and will be left untouched: {summary.conflicts.slice(0, 5).map((c) => `#${c.setter_template_id} (${c.levels.join("/")})`).join(", ")}
          {summary.conflicts.length > 5 ? `, +${summary.conflicts.length - 5} more` : ""}.
        </Banner>
      )}

      {summary.warnings.length > 0 && (
        <div>
          <button className="section-action" onClick={() => setWarningsOpen((v) => !v)}>
            {warningsOpen ? "Hide" : "Show"} warnings ({summary.warnings.length})
          </button>
          {warningsOpen && (
            <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 12, color: "var(--ink-3)" }}>
              {summary.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Two-phase: upload -> preview (nothing written yet, admin reviews
 * sheet/conflict/warning counts) -> confirm (the real, additive-only write).
 * Never auto-imports on upload — see EVENT_QUESTION_REVIEW.md. */
function ImportDialog({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  const fileRef = useRef<HTMLInputElement>(null);
  const [job, setJob] = useState<EqrImportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useImportJobPoll(job, setJob);

  async function upload() {
    const file = fileRef.current?.files?.[0];
    if (!file) { setError("Choose a .xlsx file first."); return; }
    setError(null);
    setBusy(true);
    try {
      setJob(await api.uploadEventReviewImport(file));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!job) return;
    setError(null);
    setBusy(true);
    try {
      setJob(await api.confirmEventReviewImport(job.id));
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  return (
    <dialog ref={ref} className="dialog" style={{ width: "min(640px, calc(100vw - 32px))" }} onClose={onClose} onCancel={onClose}>
      <div className="dialog-head">
        <div>
          <div className="card-title">Import review data</div>
          <div className="card-sub">
            Upload a workbook in the reference format — one sheet per event (sheet name = event slug), Setter
            Template ID + review status/reviewer columns per question.
          </div>
        </div>
        <button className="section-action" onClick={() => ref.current?.close()} aria-label="Close"><Icon d={PATH.close} size={12} /></button>
      </div>

      {!job && (
        <>
          <input ref={fileRef} type="file" accept=".xlsx" className="field" />
          {error && <p className="card-sub" style={{ color: "var(--status-critical)" }}>{error}</p>}
          <div className="btn-row" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn-secondary" onClick={() => ref.current?.close()}>Cancel</button>
            <button className="btn btn-primary" disabled={busy} onClick={upload}>{busy ? "Uploading…" : "Upload & validate"}</button>
          </div>
        </>
      )}

      {job && isImportPending(job.status) && (
        <p className="card-sub">
          {job.status === "importing" ? "Writing changes…" : `Validating ${job.filename}…`} This checks the file and never writes anything until you confirm.
        </p>
      )}

      {job && job.status === "ready_for_review" && job.preview && (
        <>
          <ImportSummaryView summary={job.preview} />
          {error && <p className="card-sub" style={{ color: "var(--status-critical)" }}>{error}</p>}
          <div className="btn-row" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn-secondary" onClick={() => ref.current?.close()}>Cancel — don't import</button>
            <button className="btn btn-primary" disabled={busy} onClick={confirm}>{busy ? "Importing…" : "Confirm import"}</button>
          </div>
        </>
      )}

      {job && job.status === "done" && job.result && (
        <>
          <Banner tone="info">Import complete.</Banner>
          <ImportSummaryView summary={job.result} />
          <div className="btn-row" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn-primary" onClick={() => { onImported(); ref.current?.close(); }}>Done</button>
          </div>
        </>
      )}

      {job && job.status === "error" && (
        <>
          <Banner tone="error">{job.error || "Import failed."}</Banner>
          <div className="btn-row" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn-secondary" onClick={() => ref.current?.close()}>Close</button>
          </div>
        </>
      )}
    </dialog>
  );
}

function BulkVerdictModal({
  count, onCancel, onSubmit,
}: { count: number; onCancel: () => void; onSubmit: (status: EqrVerdict, note: string) => Promise<void> }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);

  const [status, setStatus] = useState<EqrVerdict | "">("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const needsNote = status === "fixed" || status === "removed";

  async function submit() {
    if (!status) { setError("Choose a verdict — no default is assumed."); return; }
    if (needsNote && !note.trim()) { setError(status === "fixed" ? "Fixed needs a summary." : "Removed needs a reason."); return; }
    setSaving(true);
    try {
      await onSubmit(status, note.trim());
    } catch (e) {
      setError((e as ApiError).message);
      setSaving(false);
    }
  }

  return (
    <dialog ref={ref} className="dialog" onClose={onCancel} onCancel={onCancel}>
      <div className="dialog-head">
        <div>
          <div className="card-title">Set verdict for selected</div>
          <div className="card-sub">Applies the same verdict to all {count} selected rows.</div>
        </div>
        <button className="section-action" onClick={() => ref.current?.close()} aria-label="Close"><Icon d={PATH.close} size={12} /></button>
      </div>
      <div className="verdict-form">
        <select className="field" value={status} onChange={(e) => setStatus(e.target.value as EqrVerdict)}>
          <option value="">Choose a verdict…</option>
          <option value="no_issue_found">No issue found</option>
          <option value="fixed">Fixed</option>
          <option value="removed">Removed from library</option>
        </select>
        {status === "removed" && <RemovedWarning />}
        {needsNote && (
          <textarea className="field" placeholder="Same summary/reason applied to every selected row — required."
                    value={note} onChange={(e) => setNote(e.target.value)} />
        )}
        {error && <p className="card-sub" style={{ color: "var(--status-critical)" }}>{error}</p>}
      </div>
      <div className="btn-row" style={{ justifyContent: "flex-end" }}>
        <button className="btn btn-secondary" onClick={() => ref.current?.close()}>Cancel</button>
        <button className="btn btn-primary" disabled={saving} onClick={submit}>Apply to selected</button>
      </div>
    </dialog>
  );
}

/** A `<th>` that's both a sort toggle (click the label) and a single-value
 * filter (the select below it) — replaces what used to be a separate
 * toolbar dropdown, so there's one place to filter a column instead of two
 * that could show different states. */
function SortFilterHeader({
  label, sortActive, sortDir, onSort, options, value, onChange,
}: {
  label: string; sortActive: boolean; sortDir: "asc" | "desc"; onSort: () => void;
  options: string[]; value: string; onChange: (v: string) => void;
}) {
  return (
    <th className="eqr-sortable-th">
      <div className="eqr-th-row">
        <button className="eqr-th-sort" onClick={onSort}>
          {label}
          {sortActive && <Icon d={sortDir === "asc" ? PATH.chevronUp : PATH.chevronDown} size={10} />}
        </button>
        {/* A native select needs no outside-click handling to close itself,
            and is literally "pick one of these options" — simpler than the
            custom popover this replaced. */}
        <select
          className="eqr-th-select" aria-label={`Filter by ${label}`}
          value={value} onChange={(e) => onChange(e.target.value)}
        >
          <option value="">All</option>
          {options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>
    </th>
  );
}

function GridRow({
  row, me, isAdmin, members, slug, selected, expanded, visibleCols,
  onToggleSelect, onToggleExpand, onClaim, onChanged, onOpenHistory,
}: {
  row: EqrQuestionRow; me: Me; isAdmin: boolean; members: Member[]; slug: string;
  selected: boolean; expanded: boolean; visibleCols: Set<string>;
  onToggleSelect: (on: boolean) => void; onToggleExpand: () => void;
  onClaim: (level: "l1" | "l2") => Promise<void>;
  onChanged: (rows: EqrQuestionRow[]) => void;
  onOpenHistory: () => void;
}) {
  const id = row.setter_template_id;
  const [claiming, setClaiming] = useState<"l1" | "l2" | null>(null);
  const [claimError, setClaimError] = useState<string | null>(null);

  async function handleClaim(level: "l1" | "l2") {
    setClaimError(null);
    setClaiming(level);
    try {
      await onClaim(level);
    } catch (e) {
      setClaimError((e as ApiError).message);
    } finally {
      setClaiming(null);
    }
  }

  return (
    <>
      <tr className={selected ? "eqr-row-selected" : undefined}>
        {isAdmin && (
          <td className="eqr-sticky1"><input type="checkbox" checked={selected} onChange={(e) => onToggleSelect(e.target.checked)} /></td>
        )}
        <td className={isAdmin ? "eqr-sticky2" : "eqr-sticky1"}>
          <button className="eqr-expand-btn" onClick={onToggleExpand} aria-expanded={expanded} aria-label={expanded ? "Collapse details" : "Expand details"}>
            <Icon d={expanded ? PATH.chevronDown : PATH.chevronRight} size={12} />
          </button>
        </td>
        <td className={`eqr-mono${isAdmin ? "" : " eqr-sticky2"}`}>{id}</td>
        <td className="eqr-title-cell" title={row.title} style={{ color: "var(--ink)", fontWeight: 560, cursor: "pointer" }} onClick={onToggleExpand}>{row.title}</td>
        <td className="eqr-secondary">{row.question_type.replace("Multiple Choice Questions", "MCQ")}</td>
        <td className="eqr-secondary">{row.level}</td>
        <td>{row.l1_assignee?.display_name ?? "—"}</td>
        <td className="eqr-center">
          {!row.l1_assignee ? <span className="pill pill-muted">Unassigned</span>
            : row.l1_status === "not_started" ? (
              <button className="btn btn-secondary btn-sm" disabled={claiming === "l1"} onClick={() => handleClaim("l1")}>
                {claiming === "l1" ? "Starting…" : "Start"}
              </button>
            )
            : row.l1_status === "in_progress" ? <button className="btn btn-primary btn-sm" onClick={onToggleExpand}>In progress</button>
            : <span className="pill pill-closed">Done</span>}
        </td>
        <td>{row.l2_assignee?.display_name ?? "—"}</td>
        <td className="eqr-center">
          {row.l2_status === "not_requested" ? <span className="pill pill-muted">—</span>
            : row.l2_status === "pending" ? (
              <button className="btn btn-secondary btn-sm" disabled={claiming === "l2"} onClick={() => handleClaim("l2")}>
                {claiming === "l2" ? "Starting…" : "Start"}
              </button>
            )
            : row.l2_status === "in_progress" ? <button className="btn btn-primary btn-sm" onClick={onToggleExpand}>In progress</button>
            : <span className="pill pill-closed">Done</span>}
        </td>
        <td className="eqr-center">{row.last_verdict ? <span className={`pill pill-${STATUS_PILL[row.last_verdict]}`}>{STATUS_LABEL[row.last_verdict]}</span> : <span className="pill pill-muted">—</span>}</td>
        <td className="eqr-mono">{row.last_reviewed_at ? new Date(row.last_reviewed_at).toLocaleDateString() : "—"}</td>
        {EXTRA_COLUMNS.filter((c) => visibleCols.has(c.key as string)).map((c) => (
          <td key={String(c.key)}>{Array.isArray(row[c.key]) ? (row[c.key] as string[]).join(", ") : String(row[c.key] ?? "—")}</td>
        ))}
        {isAdmin && (
          <td className="eqr-center">
            {row.l1_status === "done" ? (
              <button className="btn btn-secondary btn-sm" onClick={onOpenHistory} aria-label="View history"><ClockIcon /></button>
            ) : <span className="pill pill-muted">—</span>}
          </td>
        )}
      </tr>
      {claimError && (
        <tr>
          <td colSpan={20} style={{ color: "var(--status-critical)", fontSize: 11.5, padding: "0 12px 8px" }}>{claimError}</td>
        </tr>
      )}
      {expanded && (
        <tr>
          <td colSpan={20} className="eqr-detail-row">
            <DetailPanel row={row} me={me} isAdmin={isAdmin} members={members} currentSlug={slug} onChanged={onChanged} onOpenHistory={onOpenHistory} />
          </td>
        </tr>
      )}
    </>
  );
}

/** Utils > Event Question Review. Paste an event URL, see which library
 * questions from Redash (query 5671) still need review, and drive the
 * L1/L2 review lifecycle — see EVENT_QUESTION_REVIEW.md. */
export function EventQuestionReview({ me }: { me: CurrentUser["member"] }) {
  const params = useParams<{ slug?: string }>();

  return (
    <>
      <div className="util-page-head">
        <Link className="btn btn-secondary" to="/utils">← Back</Link>
        <span className="util-page-title">Event Question Review</span>
      </div>
      <p className="tab-blurb">
        Paste the event's URL — we'll pull its library questions from Redash and check them against past reviews.
      </p>

      {!params.slug ? <UrlForm isAdmin={me?.role === "admin"} /> : <ResultsGrid slug={params.slug} me={me} />}
    </>
  );
}
