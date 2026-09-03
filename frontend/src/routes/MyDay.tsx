import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api";
import { DateField } from "../components/DateField";
import { LeaveCalendar } from "../components/LeaveCalendar";
import { SchedulePicker } from "../components/SchedulePicker";
import { StatusDialog } from "../components/StatusDialog";
import { Async, Banner, SectionHeading, StatTile } from "../components/ui";
import { dmy, mins, statusLabel, today as todayIso } from "../format";
import { useApi, type State } from "../hooks/useApi";
import { bumpDataVersion } from "../hooks/useDataVersion";
import type { CurrentUser, Entry, Item, Lookup, TodayStatus } from "../types";

const PARENT_KEY_PATTERN = /^[A-Z][A-Z0-9]*-\d+$/;

/** One screen for the whole day, instead of a Plan form and an Update form.
 *
 * The split was the confusing part: two buttons that looked alike, one of which
 * failed with "no plan exists" depending on the time of day. Here there is a
 * single page whose shape follows where you are — write your list in the
 * morning, report against it later, raise a ticket for anything unplanned.
 */
export function MyDay({
  me, today,
}: { me: CurrentUser["member"]; today: State<TodayStatus | null> }) {
  const isLead = me?.role === "admin" || me?.role === "manager";
  // A lead lands here from the Plan Board with ?member_id=… to open that
  // person's day directly, rather than picking them from the dropdown.
  const [params] = useSearchParams();
  const linkedMemberId = isLead ? Number(params.get("member_id")) || null : null;

  const [date, setDate] = useState(todayIso());
  const [memberId, setMemberId] = useState<number | null>(linkedMemberId ?? me?.id ?? null);
  const [justCreated, setJustCreated] = useState<Item[]>([]);
  const members = useApi(() => (isLead ? api.members() : Promise.resolve([])), [isLead]);

  const who = memberId ?? me?.id ?? null;
  const plan = useApi(
    () =>
      who
        ? api.planFor(who, date).catch((e: ApiError) => {
            if (e.code === "no_plan") return null;
            throw e;
          })
        : Promise.resolve(null),
    [who, date]
  );

  if (!me) {
    return (
      <Banner tone="warn">
        Your account isn't linked to a team member, so there's no day to log. An
        admin can link it on the Settings screen.
      </Banner>
    );
  }

  return (
    <>
      <SectionHeading
        title="My day"
        color="var(--accent-aqua)"
        action={
          <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {isLead ? (
              <select
                className="field"
                style={{ width: "auto" }}
                value={who ?? ""}
                onChange={(e) => setMemberId(Number(e.target.value))}
                aria-label="Member"
              >
                {(members.data ?? []).map((m) => (
                  <option key={m.id} value={m.id}>{m.display_name}</option>
                ))}
              </select>
            ) : null}
            <DateField
              value={date}
              max={todayIso()}
              ariaLabel="Date"
              onChange={(iso) => iso && setDate(iso)}
            />
          </span>
        }
      />

      {who ? <MarkLeave memberId={who} today={today} /> : null}

      <Async loading={plan.loading} error={plan.error} data={{ plan: plan.data }}>
        {({ plan: existing }) =>
          // A Jira-sync mirror (an externally-assigned ticket parked here,
          // never filed by the person) isn't a real plan — treat it the
          // same as no plan yet, so "Plan your day" still shows.
          existing && existing.source !== "jira" ? (
            <DayInProgress
              plan={existing}
              date={date}
              memberId={who!}
              onChange={plan.reload}
              justCreated={justCreated}
              setJustCreated={setJustCreated}
              canDelete={me.role === "admin"}
            />
          ) : (
            <StartTheDay
              memberId={who!}
              date={date}
              // Jira may have already parked externally-assigned tickets here
              // (see services.entries.create_plan) — surface them so the
              // person can see what's already on their day, and so the plan
              // can be set even if every one of today's tickets came from
              // Jira and nothing new needs typing.
              jiraItems={existing?.items ?? []}
              onCreated={(items) => { setJustCreated(items); plan.reload(); bumpDataVersion(); }}
            />
          )
        }
      </Async>
    </>
  );
}

/* ── leave: say you won't be working, without saying it every morning ───── */

/** A person's own leave days, current date onward. Marking one here is what
 * keeps the Slack roll call from nagging them for a plan and from pinging
 * them by name — they're still named, just not tagged. */
function MarkLeave({
  memberId, today,
}: { memberId: number; today: State<TodayStatus | null> }) {
  const leaves = useApi(() => api.myLeaves(memberId), [memberId]);
  const [open, setOpen] = useState(false);
  const dates = leaves.data?.dates ?? [];
  const nextHoliday = today.data?.next_holiday;
  const onLeaveToday = today.data?.on_leave_today ?? [];

  async function unmark(iso: string) {
    await api.unmarkLeave(iso, memberId);
    leaves.reload();
  }

  return (
    <div className="card leave-card">
      <div className="card-head">
        <div>
          <div className="card-title">On leave</div>
          <div className="card-sub">
            {dates.length
              ? `Not working on ${dates.length} upcoming day${dates.length > 1 ? "s" : ""} — named in the roll call, never tagged.`
              : "Mark any upcoming day off — named in the roll call, never tagged."}
          </div>
        </div>
        <button className="section-action" onClick={() => setOpen(true)}>
          {dates.length ? "Edit" : "+ Mark leave"}
        </button>
      </div>

      {nextHoliday ? (
        <div className="leave-chips">
          <span className="holiday-badge">
            <span className="holiday-badge-icon" aria-hidden="true">🗓️</span>
            Next holiday: {nextHoliday.name}
            <span className="mono">{dmy(nextHoliday.date)}</span>
          </span>
        </div>
      ) : null}

      {onLeaveToday.length ? (
        <div className="card-sub" style={{ marginTop: 10 }}>
          On leave today: {onLeaveToday.map((m) => m.member).join(", ")}
        </div>
      ) : null}

      {dates.length ? (
        <div className="leave-chips">
          {dates.map((iso) => (
            <span className="leave-chip" key={iso}>
              <span className="leave-chip-icon" aria-hidden="true">🗓️</span>
              {dmy(iso)}
              <button type="button" aria-label={`Unmark ${dmy(iso)}`} onClick={() => unmark(iso)}>
                ✕
              </button>
            </span>
          ))}
        </div>
      ) : null}

      {open ? (
        <LeaveCalendarDialog
          memberId={memberId}
          saved={dates}
          onClose={() => setOpen(false)}
          onSaved={() => {
            setOpen(false);
            leaves.reload();
          }}
        />
      ) : null}
    </div>
  );
}

/** Selections here are pending until Save — clicking a date only updates the
 * grid, so nothing is written until the choice is actually final. */
function LeaveCalendarDialog({
  memberId, saved, onClose, onSaved,
}: { memberId: number; saved: string[]; onClose: () => void; onSaved: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [pending, setPending] = useState(saved);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  const dirty = pending.length !== saved.length || pending.some((d) => !saved.includes(d));

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const added = pending.filter((d) => !saved.includes(d));
      const removed = saved.filter((d) => !pending.includes(d));
      await Promise.all([
        ...(added.length ? [api.markLeave(added, memberId)] : []),
        ...removed.map((d) => api.unmarkLeave(d, memberId)),
      ]);
      onSaved();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setSaving(false);
    }
  }

  return (
    <dialog ref={ref} className="dialog leave-dialog" onClose={onClose} onCancel={onClose}>
      <div className="dialog-head">
        <span className="card-title">Mark leave</span>
        <button className="section-action" aria-label="Close" onClick={onClose}>✕</button>
      </div>

      {error ? <Banner tone="error">{error.message}</Banner> : null}

      <LeaveCalendar
        selected={pending}
        onToggle={(iso) =>
          setPending((ds) => (ds.includes(iso) ? ds.filter((d) => d !== iso) : [...ds, iso].sort()))
        }
      />

      <div className="btn-row" style={{ marginTop: 14 }}>
        <span className="topbar-spacer" />
        <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!dirty || saving} onClick={save}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </dialog>
  );
}

/* ── morning: write the list ─────────────────────────────────────────────── */

interface Draft {
  pipeline: string;
  task_type_id: string;
  question_type_ids: number[];
  customer: string;
  count: string;
  due_at: string;
  notes: string;
  parent_issue_key: string;
  create_jira: boolean;
}

const blank = (): Draft => ({
  pipeline: "content_task",
  task_type_id: "", question_type_ids: [], customer: "", count: "",
  due_at: todayIso(), notes: "", parent_issue_key: "",
  // On by default — most planned work is meant to become a Jira ticket;
  // still a checkbox, so the exception is one click away.
  create_jira: true,
});

/** Looks exactly like the old single-answer dropdown when closed — same
 * `.field` box, same size. Native `<select multiple>` only adds an option
 * to the selection on Ctrl/Cmd-click, which isn't discoverable, so this
 * opens a plain checkbox list instead: click any number of rows, no
 * modifier key needed. */
function QuestionTypePicker({
  options, selected, onChange,
}: { options: Lookup[]; selected: number[]; onChange: (ids: number[]) => void }) {
  const label = options.filter((t) => selected.includes(t.id)).map((t) => t.name).join(", ");
  return (
    <details className="qtype-select">
      <summary className="field">{label || "—"}</summary>
      <div className="qtype-menu">
        {options.map((t) => (
          <label key={t.id} className="check">
            <input
              type="checkbox"
              checked={selected.includes(t.id)}
              onChange={() =>
                onChange(selected.includes(t.id)
                  ? selected.filter((id) => id !== t.id)
                  : [...selected, t.id])}
            />
            <span>{t.name}</span>
          </label>
        ))}
      </div>
    </details>
  );
}

function StartTheDay({
  memberId, date, jiraItems, onCreated,
}: {
  memberId: number; date: string; jiraItems: Item[]; onCreated: (items: Item[]) => void;
}) {
  const workTypes = useApi(() => api.workTypes(), []);
  const taskTypes = useApi(() => api.taskTypes(), []);
  const questionTypes = useApi(() => api.questionTypes(), []);
  const [rows, setRows] = useState<Draft[]>([blank()]);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  const [postAt, setPostAt] = useState("");

  const patch = (i: number, key: keyof Draft, value: string | boolean) =>
    setRows((rs) => rs.map((r, j) => (i === j ? { ...r, [key]: value } : r)));
  const setQuestionTypes = (i: number, ids: number[]) =>
    setRows((rs) => rs.map((r, j) => (i === j ? { ...r, question_type_ids: ids } : r)));
  const filled = rows.filter((r) => r.task_type_id);
  // A row someone has started typing into — customer, count, question types,
  // a parent ticket — but never picked a task type for. `filled` above just
  // drops these silently on save (no error, no ticket, no trace), which is
  // exactly the "where did that one go" report this guards against.
  const touched = (r: Draft) =>
    Boolean(r.notes.trim() || r.customer.trim() || r.count || r.question_type_ids.length || r.parent_issue_key.trim());
  const missingTaskType = (r: Draft) => touched(r) && !r.task_type_id;
  const incomplete = (r: Draft) =>
    Boolean(r.task_type_id) &&
    (!r.due_at || !r.notes.trim() ||
      (r.pipeline === "content_request" && !PARENT_KEY_PATTERN.test(r.parent_issue_key.trim())));
  const hasIncomplete = rows.some((r) => incomplete(r) || missingTaskType(r));
  // Nothing new to type is fine — Jira may already be the whole day's work,
  // and there has to be some way to set the plan without inventing a task.
  const nothingToSave = filled.length === 0 && jiraItems.length === 0;

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const entry = await api.createPlan({
        member_id: memberId,
        entry_date: date,
        post_at: postAt || null,
        items: filled.map((r) => ({
          task_type_id: Number(r.task_type_id),
          pipeline: r.pipeline,
          question_type_ids: r.question_type_ids,
          customer: r.customer || null,
          count: r.count ? Number(r.count) : null,
          due_at: r.due_at || null,
          notes: r.notes || null,
          parent_issue_key: r.pipeline === "content_request" ? r.parent_issue_key.trim() : null,
          create_jira: r.create_jira,
        })),
      });
      onCreated(entry.items);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <p className="insight">
        <strong>Nothing planned for {date} yet.</strong> List what you're picking
        up — you'll report against it here later, and can raise tickets for anything
        unplanned then too.
      </p>

      {jiraItems.length > 0 ? (
        <div className="card" style={{ marginBottom: 12 }}>
          <div className="card-head">
            <div>
              <div className="card-title">
                Already assigned via Jira — {jiraItems.length} ticket{jiraItems.length > 1 ? "s" : ""}
              </div>
              <div className="card-sub">
                Counted whether or not you add anything else below.
              </div>
            </div>
          </div>
          {jiraItems.map((it) => (
            <div className="admin-row" key={it.id}>
              <span>
                <span className={`pill pill-${it.status}`}>{statusLabel(it.status)}</span>{" "}
                {it.task_type}
                {it.customer ? ` — ${it.customer}` : ""}
              </span>
              <span className="mono muted">{it.jira_issue_key}</span>
              <span className="muted">{it.work_type}</span>
            </div>
          ))}
        </div>
      ) : null}

      {error ? <Banner tone="error">{error.message}</Banner> : null}

      {rows.map((row, i) => (
        <div className="task-row plan-line" key={i}>
          <div>
            <label className="label">Work type *</label>
            <select className="field" value={row.pipeline}
                    onChange={(e) => patch(i, "pipeline", e.target.value)}>
              {(workTypes.data ?? []).map((w) => (
                <option key={w.key} value={w.key}>{w.label}</option>
              ))}
            </select>
          </div>
          <div style={{ position: "relative" }}>
            <label className="label">Task type *</label>
            <select
              className={`field${missingTaskType(row) ? " is-invalid" : ""}`}
              value={row.task_type_id}
              aria-invalid={missingTaskType(row) || undefined}
              onChange={(e) => patch(i, "task_type_id", e.target.value)}
            >
              <option value="">Pick a task type…</option>
              {(taskTypes.data ?? []).map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            {missingTaskType(row) ? (
              <span className="field-callout" role="alert">
                Pick a task type — this row won't be saved without one.
              </span>
            ) : null}
          </div>
          <div>
            <label className="label">Question type</label>
            <QuestionTypePicker
              options={questionTypes.data ?? []}
              selected={row.question_type_ids}
              onChange={(ids) => setQuestionTypes(i, ids)}
            />
          </div>
          <div>
            <label className="label">Customer</label>
            <input className="field" value={row.customer} placeholder="e.g. Entri"
                   onChange={(e) => patch(i, "customer", e.target.value)} />
          </div>
          <div>
            <label className="label">Count</label>
            <input className="field" type="number" min={1} value={row.count}
                   onChange={(e) => patch(i, "count", e.target.value)} />
          </div>
          <div>
            <label className="label">Due date *</label>
            <DateField
              value={row.due_at}
              ariaLabel="Due date"
              onChange={(iso) => patch(i, "due_at", iso)}
            />
          </div>
          {row.pipeline === "content_request" ? (
            <div>
              <label className="label">Parent ticket *</label>
              <input className="field" value={row.parent_issue_key} placeholder="e.g. TCE-1234"
                     onChange={(e) => patch(i, "parent_issue_key", e.target.value)} />
            </div>
          ) : null}
          <div className="task-row-wide">
            <label className="label">Summary *</label>
            <textarea className="field" rows={2} value={row.notes}
                      onChange={(e) => patch(i, "notes", e.target.value)} />
          </div>
          {incomplete(row) ? (
            <div className="task-row-wide">
              <span className="hint" style={{ color: "var(--status-critical)" }}>
                Due date, summary
                {row.pipeline === "content_request" ? ", and a valid parent ticket (e.g. TCE-1234)" : ""}
                {" "}are required before this can be saved.
              </span>
            </div>
          ) : missingTaskType(row) ? (
            <div className="task-row-wide">
              <span className="hint" style={{ color: "var(--status-critical)" }}>
                Task type is required before this can be saved.
              </span>
            </div>
          ) : null}
          <div className="task-row-wide">
            <label className="check">
              <input type="checkbox" checked={row.create_jira}
                     onChange={(e) => patch(i, "create_jira", e.target.checked)} />
              <span>Raise a Jira ticket for this</span>
            </label>
          </div>
        </div>
      ))}

      {/* Written now, announced later. */}
      <SchedulePicker value={postAt} onChange={setPostAt} />

      <div className="btn-row">
        <button className="btn btn-secondary" onClick={() => setRows((r) => [...r, blank()])}>
          + Another task
        </button>
        {rows.length > 1 ? (
          <button className="btn btn-secondary" onClick={() => setRows((r) => r.slice(0, -1))}>
            Remove last
          </button>
        ) : null}
        <span className="topbar-spacer" />
        <span className="muted">{filled.length} ready</span>
        <button
          className="btn btn-primary"
          disabled={saving || nothingToSave || hasIncomplete}
          onClick={save}
        >
          {saving
            ? "Saving…"
            : filled.length ? "Start the day" : "Confirm today's plan"}
        </button>
      </div>
    </>
  );
}

/* ── later: report against it ────────────────────────────────────────────── */

function DayInProgress({
  plan, date, memberId, onChange, justCreated, setJustCreated, canDelete,
}: {
  plan: Entry; date: string; memberId: number; onChange: () => void;
  justCreated: Item[]; setJustCreated: (items: Item[]) => void; canDelete: boolean;
}) {
  const taskTypes = useApi(() => api.taskTypes(), []);
  const [moving, setMoving] = useState<Item | null>(null);
  const [ticketing, setTicketing] = useState(false);

  // Unplanned work lands on its own "update" entry(ies), which the plan we
  // loaded never includes — fetched separately so every ticket raised today
  // still shows up after a refresh, not just for the session that created it.
  const updates = useApi(
    () => api.entries({ member_id: memberId, from: date, to: date, kind: "update" }),
    [memberId, date]
  );
  const loggedExtras = (updates.data?.items ?? [])
    .flatMap((e) => e.items)
    .filter((it) => it.plan_item_id === null);
  const extrasPending = loggedExtras.some((it) => it.jira_state === "pending");

  // A ticket just raised is created in the background, so the plan we just
  // loaded still shows it as "pending". Poll until Jira has actually answered,
  // then reload once to pick up the real key — instead of leaving the row
  // showing nothing until the next manual refresh.
  useEffect(() => {
    if (!plan.items.some((i) => i.jira_state === "pending")) return;
    const id = setInterval(async () => {
      const { pending } = await api.jiraState(plan.id);
      if (!pending) onChange();
    }, 3000);
    return () => clearInterval(id);
  }, [plan.id, plan.items, onChange]);

  // Same idea, for unplanned work — refetches the whole (small) list rather
  // than patching one item, since a day can carry more than one update entry.
  useEffect(() => {
    if (!extrasPending) return;
    const id = setInterval(() => updates.reload(), 3000);
    return () => clearInterval(id);
  }, [extrasPending, updates.reload]);

  const allItems = [...plan.items, ...loggedExtras];
  const done = allItems.filter((i) => i.status === "closed").length;

  function onSaved() {
    setMoving(null);
    onChange();
    updates.reload();
    bumpDataVersion();
  }

  return (
    <>
      <div className="stat-row">
        <StatTile label="Planned" value={plan.items.length} accent="var(--accent-indigo)" />
        <StatTile label="Done" value={done} accent="var(--accent-aqua)" />
        <StatTile
          label="Effort so far"
          value={mins(allItems.reduce((s, i) => s + (i.effort_minutes ?? 0), 0) || null)}
          accent="var(--accent-orange)"
        />
      </div>

      {justCreated.length ? (
        <div className="card" style={{ marginBottom: 12 }}>
          <div className="card-head">
            <div className="card-title">Just created</div>
            <button className="section-action" onClick={() => setJustCreated([])} aria-label="Dismiss">✕</button>
          </div>
          {justCreated.map((it) => (
            <p key={it.id} className="insight" style={{ marginTop: 4 }}>
              <strong>{it.title}</strong>
              <br />
              {it.work_type} · {it.task_type}
              {it.customer ? ` · ${it.customer}` : ""}
              {it.due_at ? ` · due ${it.due_at}` : ""}
              {it.jira_issue_key ? (
                <> · <a className="tag" href={it.jira_issue_url ?? "#"} target="_blank" rel="noreferrer">
                  {it.jira_issue_key}
                </a></>
              ) : null}
              {it.parent_issue_key ? (
                <> · parent <a className="tag" href={it.parent_issue_url ?? "#"} target="_blank" rel="noreferrer">
                  {it.parent_issue_key}
                </a></>
              ) : null}
            </p>
          ))}
        </div>
      ) : null}

      <SectionHeading
        title="How today's going"
        color="var(--accent-indigo)"
        action={
          <button className="btn btn-secondary" onClick={() => setTicketing(true)}>
            + New ticket
          </button>
        }
      />

      {/* One row per task, entirely read-only — every edit (status, effort,
          due date, task type) goes through "Move status" now, so there's one
          place that knows the workflow rules instead of two that could drift. */}
      <div className="table-scroll day-table">
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Task</th>
              <th>Stream</th>
              <th>Customer</th>
              <th className="num">Effort (m)</th>
              <th>Due</th>
              <th>Summary</th>
            </tr>
          </thead>
          <tbody>
            {allItems.map((item) => (
              <TicketRow key={item.id} item={item} onMove={() => setMoving(item)} />
            ))}
          </tbody>
        </table>
      </div>

      {moving ? (
        <StatusDialog item={moving} onClose={() => setMoving(null)} onSaved={onSaved}
                      canDelete={canDelete} />
      ) : null}

      {ticketing ? (
        <NewTicketDialog
          memberId={memberId}
          date={date}
          taskTypes={taskTypes.data ?? []}
          onClose={() => setTicketing(false)}
          onCreated={(items) => { setJustCreated(items); onChange(); updates.reload(); bumpDataVersion(); }}
        />
      ) : null}
    </>
  );
}

function TicketRow({ item, onMove }: { item: Item; onMove: () => void }) {
  return (
    <tr>
      <td>
        <button className={`pill pill-${item.status} pill-button`} onClick={onMove} title="Move status">
          {statusLabel(item.status)}
        </button>
      </td>
      <td className="text">
        <span className="day-task">{item.task_type}</span>
        {item.jira_issue_key && item.jira_missing ? (
          <span className="pill pill-blocked" title="No longer found in Jira — it was deleted there">
            removed in Jira
          </span>
        ) : item.jira_issue_key ? (
          <>
            <a className="tag" href={item.jira_issue_url ?? "#"} target="_blank"
               rel="noreferrer">{item.jira_issue_key}</a>
            {/* The ticket itself exists — jira_state is "ok" — but linking it
                to its parent can still fail on its own. Surfaced here rather
                than silently, since an unlinked split-off ticket defeats the
                reason a parent was asked for in the first place. */}
            {item.jira_error ? (
              <span className="pill pill-warn" title={item.jira_error}>
                not linked to parent
              </span>
            ) : null}
          </>
        ) : item.jira_state === "pending" ? (
          <span className="pill pill-muted">syncing…</span>
        ) : item.jira_state === "failed" ? (
          <>
            <span className="pill pill-blocked">failed</span>
            <div className="hint" style={{ color: "var(--status-critical)" }}>
              {item.jira_error ?? "Jira ticket creation failed"}
            </div>
          </>
        ) : null}
        {item.parent_issue_key ? (
          <a className="tag" href={item.parent_issue_url ?? "#"} target="_blank" rel="noreferrer"
             title="Parent ticket">↑ {item.parent_issue_key}</a>
        ) : null}
      </td>
      <td className="muted">{item.work_type}</td>
      <td>{item.customer ?? <span className="muted">—</span>}</td>
      <td className="num">{mins(item.effort_minutes)}</td>
      <td className="mono muted">{dmy(item.due_at)}</td>
      <td className="text">{item.notes ?? <span className="muted">—</span>}</td>
    </tr>
  );
}

/** A ticket is its own thing, not a row in the day's report — same fields,
 * same Jira/scheduling options as the morning plan, saved in one step. */
function NewTicketDialog({
  memberId, date, taskTypes, onClose, onCreated,
}: {
  memberId: number; date: string; taskTypes: Lookup[]; onClose: () => void;
  onCreated: (items: Item[]) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const workTypes = useApi(() => api.workTypes(), []);
  const questionTypes = useApi(() => api.questionTypes(), []);
  const [pipeline, setPipeline] = useState("content_task");
  const [taskTypeId, setTaskTypeId] = useState("");
  const [questionTypeIds, setQuestionTypeIds] = useState<number[]>([]);
  const [customer, setCustomer] = useState("");
  const [count, setCount] = useState("");
  const [dueAt, setDueAt] = useState(todayIso());
  const [notes, setNotes] = useState("");
  const [parentIssueKey, setParentIssueKey] = useState("");
  // Same default as the morning plan — on, still a checkbox to opt out.
  const [createJira, setCreateJira] = useState(true);
  const [postAt, setPostAt] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  const isContentRequest = pipeline === "content_request";
  const parentValid = !isContentRequest || PARENT_KEY_PATTERN.test(parentIssueKey.trim());

  async function create() {
    setError(null);
    setSaving(true);
    try {
      const entry = await api.createUpdate({
        member_id: memberId,
        entry_date: date,
        post_at: postAt || null,
        plan_lines: [],
        extra_items: [{
          task_type_id: Number(taskTypeId),
          pipeline,
          question_type_ids: questionTypeIds,
          customer: customer || null,
          count: count ? Number(count) : null,
          due_at: dueAt,
          notes: notes.trim(),
          parent_issue_key: isContentRequest ? parentIssueKey.trim() : null,
          effort_minutes: null,
          create_jira: createJira,
        }],
      });
      onCreated(entry.items);
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
          <div className="card-title">New ticket</div>
          <div className="card-sub">Same options as the morning plan — logs it and closes.</div>
        </div>
        <button className="section-action" onClick={onClose} aria-label="Close">✕</button>
      </div>

      {error ? <Banner tone="error">{error.message}</Banner> : null}

      <label className="label">Work type *</label>
      <select className="field" value={pipeline} onChange={(e) => setPipeline(e.target.value)}>
        {(workTypes.data ?? []).map((w) => (
          <option key={w.key} value={w.key}>{w.label}</option>
        ))}
      </select>

      <label className="label" style={{ marginTop: 12 }}>Task type *</label>
      <select className="field" value={taskTypeId} onChange={(e) => setTaskTypeId(e.target.value)}>
        <option value="">Pick a task type…</option>
        {taskTypes.map((t) => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </select>

      <label className="label" style={{ marginTop: 12 }}>Question type</label>
      <QuestionTypePicker
        options={questionTypes.data ?? []}
        selected={questionTypeIds}
        onChange={setQuestionTypeIds}
      />

      <label className="label" style={{ marginTop: 12 }}>Customer</label>
      <input className="field" value={customer} onChange={(e) => setCustomer(e.target.value)} />

      <label className="label" style={{ marginTop: 12 }}>Count</label>
      <input className="field" type="number" min={1} value={count} onChange={(e) => setCount(e.target.value)} />

      <label className="label" style={{ marginTop: 12 }}>Due date *</label>
      <DateField value={dueAt} ariaLabel="Due date" onChange={setDueAt} />

      {isContentRequest ? (
        <>
          <label className="label" style={{ marginTop: 12 }}>Parent ticket *</label>
          <input className="field" value={parentIssueKey} placeholder="e.g. TCE-1234"
                 onChange={(e) => setParentIssueKey(e.target.value)} />
        </>
      ) : null}

      <label className="label" style={{ marginTop: 12 }}>Summary *</label>
      <textarea className="field" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />

      <label className="check" style={{ marginTop: 12 }}>
        <input type="checkbox" checked={createJira} onChange={(e) => setCreateJira(e.target.checked)} />
        <span>Raise a Jira ticket for this</span>
      </label>

      {/* Written now, announced later. */}
      <SchedulePicker value={postAt} onChange={setPostAt} />

      <div className="btn-row">
        <span className="topbar-spacer" />
        <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button
          className="btn btn-primary"
          disabled={saving || !taskTypeId || !dueAt || !notes.trim() || !parentValid}
          onClick={create}
        >
          {saving ? "Creating…" : "Create ticket"}
        </button>
      </div>
    </dialog>
  );
}
