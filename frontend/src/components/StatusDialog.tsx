import { useEffect, useRef, useState } from "react";
import { DateField } from "./DateField";
import { ApiError, api } from "../api";
import { statusLabel, today } from "../format";
import type { Item, Status } from "../types";
import { Banner } from "./ui";
import { useApi } from "../hooks/useApi";

/** A ticket earns its way through the workflow — it can't jump straight from
 * Open to Done/Blocked, and once Done it's done for good. Mirrors
 * services.entries.ALLOWED_TRANSITIONS on the backend, which is the version
 * that actually gets enforced; this one just keeps the UI from offering a
 * move the server would reject anyway. */
const ALLOWED_NEXT: Record<Status, Status[]> = {
  open: ["in_progress"],
  in_progress: ["blocked", "closed"],
  blocked: ["in_progress"],
  closed: [],
};

/** Moving a task through its workflow, with a mandatory note about *why* —
 * separate from the ticket's own Summary, which this dialog can also edit. */
export function StatusDialog({
  item,
  onClose,
  onSaved,
}: {
  item: Item;
  onClose: () => void;
  onSaved: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const taskTypes = useApi(() => api.taskTypes(), []);
  const [taskTypeId, setTaskTypeId] = useState(String(item.task_type_id));
  const [status, setStatus] = useState<Status>(item.status);
  const [summary, setSummary] = useState(item.notes ?? "");
  const [comment, setComment] = useState("");
  const [dueAt, setDueAt] = useState(item.due_at ?? today());
  const [effort, setEffort] = useState(item.effort_minutes?.toString() ?? "");
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  // <dialog showModal> gives focus trapping, Escape, and the backdrop for free.
  useEffect(() => {
    ref.current?.showModal();
  }, []);

  const statusChanged = status !== item.status;
  const nextOptions = [item.status, ...ALLOWED_NEXT[item.status]];
  const commentMissing = statusChanged && !comment.trim();
  // Leaving in-progress is where time was actually spent — require it here,
  // not at some vaguer "before you can close this" moment.
  const effortMissing = item.status === "in_progress" && statusChanged && effort === "";

  const nothingChanged =
    !statusChanged &&
    taskTypeId === String(item.task_type_id) &&
    summary === (item.notes ?? "") &&
    dueAt === (item.due_at ?? today()) &&
    effort === (item.effort_minutes?.toString() ?? "");

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.patchItem(item.id, {
        status,
        task_type_id: Number(taskTypeId),
        notes: summary.trim() || null,
        comment: comment.trim() || null,
        due_at: dueAt || null,
        effort_minutes: effort === "" ? null : Number(effort),
      });
      onSaved();
      onClose();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    const warning = item.jira_issue_key
      ? `Delete this ticket and cancel ${item.jira_issue_key} in Jira? This can't be undone.`
      : "Delete this ticket? This can't be undone.";
    if (!window.confirm(warning)) return;
    setError(null);
    setSaving(true);
    try {
      await api.deleteItem(item.id);
      onSaved();
      onClose();
    } catch (e) {
      setError(e as ApiError);
      setSaving(false);
    }
  }

  return (
    <dialog ref={ref} className="dialog" onClose={onClose} onCancel={onClose}>
      <div className="dialog-head">
        <div>
          <div className="card-title">{item.task_type}</div>
          <div className="card-sub">
            {item.customer ? `${item.customer} · ` : ""}currently {statusLabel(item.status)}
          </div>
        </div>
        <button className="section-action" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>

      {error ? <Banner tone="error">{error.message}</Banner> : null}

      <label className="label" htmlFor="dlg-task-type">Task type</label>
      <select
        id="dlg-task-type"
        className="field"
        value={taskTypeId}
        onChange={(e) => setTaskTypeId(e.target.value)}
      >
        {(taskTypes.data ?? []).map((t) => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </select>

      {nextOptions.length > 1 ? (
        <>
          <label className="label" style={{ marginTop: 12 }}>Move to</label>
          <div className="period-group" style={{ marginBottom: 12, width: "fit-content" }}>
            {nextOptions.map((s) => (
              <button
                key={s}
                className="period-btn"
                aria-pressed={status === s}
                onClick={() => setStatus(s)}
              >
                {statusLabel(s)}
              </button>
            ))}
          </div>
        </>
      ) : (
        <p className="hint" style={{ marginTop: 12 }}>Done is final — this can't move any further.</p>
      )}

      <label className="label" htmlFor="dlg-due">
        Due date
      </label>
      <DateField id="dlg-due" label="due date" value={dueAt} onChange={setDueAt} />

      <label className="label" style={{ marginTop: 12 }} htmlFor="dlg-effort">
        Effort (min) — total for this task, not an addition
        {item.status === "in_progress" ? " *" : ""}
      </label>
      <input
        id="dlg-effort"
        className={`field${effortMissing ? " is-invalid" : ""}`}
        type="number"
        min={0}
        step={5}
        value={effort}
        onChange={(e) => setEffort(e.target.value)}
      />
      {effortMissing ? (
        <span className="hint" style={{ color: "var(--status-critical)" }}>
          Log the effort spent before moving this off In progress.
        </span>
      ) : null}

      <label className="label" style={{ marginTop: 12 }} htmlFor="dlg-summary">
        Summary
      </label>
      <textarea
        id="dlg-summary"
        className="field"
        rows={3}
        value={summary}
        onChange={(e) => setSummary(e.target.value)}
        placeholder="Shown on the dashboard, and synced to Jira"
      />

      {nextOptions.length > 1 ? (
        <>
          <label className="label" style={{ marginTop: 12 }} htmlFor="dlg-comment">
            Comment{statusChanged ? " *" : ""}
          </label>
          <textarea
            id="dlg-comment"
            className={`field${commentMissing ? " is-invalid" : ""}`}
            rows={2}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="What happened, or why it's moving — posted to Jira as a comment"
          />
          {commentMissing ? (
            <span className="hint" style={{ color: "var(--status-critical)" }}>
              A comment is required when moving status.
            </span>
          ) : null}
        </>
      ) : null}

      <div className="btn-row">
        <span className="muted">
          {item.jira_issue_key ? `Syncs ${item.jira_issue_key}` : "Not linked to Jira"}
        </span>
        <span className="topbar-spacer" />
        <button className="btn btn-danger" disabled={saving} onClick={remove}>
          Delete
        </button>
        <button className="btn btn-secondary" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={saving || nothingChanged || commentMissing || effortMissing}
          onClick={save}
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </dialog>
  );
}
