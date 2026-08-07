import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { statusLabel } from "../format";
import type { Item, Status } from "../types";
import { Banner } from "./ui";

const OPTIONS: Status[] = ["open", "in_progress", "blocked", "closed"];

/** Moving a task. The note becomes a Jira comment, and the due date is what the
 * TCE workflow demands on a transition — same contract as the Django modal. */
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
  const [status, setStatus] = useState<Status>(item.status);
  const [notes, setNotes] = useState("");
  const [dueAt, setDueAt] = useState(item.due_at ?? "");
  const [effort, setEffort] = useState(item.effort_minutes?.toString() ?? "");
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  // <dialog showModal> gives focus trapping, Escape, and the backdrop for free.
  useEffect(() => {
    ref.current?.showModal();
  }, []);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.patchItem(item.id, {
        status,
        notes: notes.trim() || null,
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

      <label className="label">Move to</label>
      <div className="period-group" style={{ marginBottom: 12, width: "fit-content" }}>
        {OPTIONS.map((s) => (
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

      <label className="label" htmlFor="dlg-due">
        Due date
      </label>
      <input
        id="dlg-due"
        className="field"
        type="date"
        value={dueAt}
        onChange={(e) => setDueAt(e.target.value)}
      />

      <label className="label" style={{ marginTop: 12 }} htmlFor="dlg-effort">
        Effort (min) — total for this task, not an addition
      </label>
      <input
        id="dlg-effort"
        className="field"
        type="number"
        min={0}
        step={5}
        value={effort}
        onChange={(e) => setEffort(e.target.value)}
      />

      <label className="label" style={{ marginTop: 12 }} htmlFor="dlg-note">
        Comment
      </label>
      <textarea
        id="dlg-note"
        className="field"
        rows={3}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Posted to Jira as a comment"
      />

      <div className="btn-row">
        <span className="muted">
          {item.jira_issue_key ? `Syncs ${item.jira_issue_key}` : "Not linked to Jira"}
        </span>
        <span className="topbar-spacer" />
        <button className="btn btn-secondary" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={saving || (status === item.status && effort === (item.effort_minutes?.toString() ?? ""))}
          onClick={save}
        >
          {saving ? "Saving…" : "Move"}
        </button>
      </div>
    </dialog>
  );
}
