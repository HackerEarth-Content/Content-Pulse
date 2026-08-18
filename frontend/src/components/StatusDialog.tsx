import { useEffect, useRef, useState } from "react";
import { DateField } from "./DateField";
import { ApiError, api } from "../api";
import { statusLabel } from "../format";
import type { Item, Status } from "../types";
import { Banner } from "./ui";
import { useApi } from "../hooks/useApi";

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
  const taskTypes = useApi(() => api.taskTypes(), []);
  const [taskTypeId, setTaskTypeId] = useState(String(item.task_type_id));
  const [status, setStatus] = useState<Status>(item.status);
  const [notes, setNotes] = useState(item.notes ?? "");
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
        task_type_id: Number(taskTypeId),
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

      <label className="label" style={{ marginTop: 12 }}>Move to</label>
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
      <DateField id="dlg-due" label="due date" value={dueAt} onChange={setDueAt} />

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
        Summary
      </label>
      <textarea
        id="dlg-note"
        className="field"
        rows={3}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Shown on the dashboard, and synced to Jira"
      />

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
          disabled={
            saving ||
            (status === item.status &&
              taskTypeId === String(item.task_type_id) &&
              notes === (item.notes ?? "") &&
              effort === (item.effort_minutes?.toString() ?? ""))
          }
          onClick={save}
        >
          {saving ? "Saving…" : "Move"}
        </button>
      </div>
    </dialog>
  );
}
