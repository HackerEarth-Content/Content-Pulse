import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { DateField } from "../components/DateField";
import { SchedulePicker } from "../components/SchedulePicker";
import { StatusDialog } from "../components/StatusDialog";
import { Async, Banner, SectionHeading, StatTile } from "../components/ui";
import { dmy, mins, statusLabel, today } from "../format";
import { useApi } from "../hooks/useApi";
import type { CurrentUser, Entry, Item, Lookup, Status } from "../types";

/** One screen for the whole day, instead of a Plan form and an Update form.
 *
 * The split was the confusing part: two buttons that looked alike, one of which
 * failed with "no plan exists" depending on the time of day. Here there is a
 * single page whose shape follows where you are — write your list in the
 * morning, report against it later, raise a ticket for anything unplanned.
 */
export function MyDay({ me }: { me: CurrentUser["member"] }) {
  const [date, setDate] = useState(today());
  const [memberId, setMemberId] = useState<number | null>(me?.id ?? null);
  const isLead = me?.role === "admin" || me?.role === "manager";
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
              max={today()}
              ariaLabel="Date"
              onChange={(iso) => iso && setDate(iso)}
            />
          </span>
        }
      />

      <Async loading={plan.loading} error={plan.error} data={{ plan: plan.data }}>
        {({ plan: existing }) =>
          existing ? (
            <DayInProgress plan={existing} date={date} memberId={who!} onChange={plan.reload} />
          ) : (
            <StartTheDay memberId={who!} date={date} onCreated={plan.reload} />
          )
        }
      </Async>
    </>
  );
}

/* ── morning: write the list ─────────────────────────────────────────────── */

interface Draft {
  task_type_id: string;
  question_type_id: string;
  customer: string;
  count: string;
  due_at: string;
  notes: string;
  create_jira: boolean;
}

const blank = (): Draft => ({
  task_type_id: "", question_type_id: "", customer: "", count: "", due_at: "", notes: "",
  // Off by default. Plenty of logged work has no business being a ticket, and
  // an unwanted ticket is far more annoying to undo than a wanted one is to ask for.
  create_jira: false,
});

function StartTheDay({
  memberId, date, onCreated,
}: { memberId: number; date: string; onCreated: () => void }) {
  const taskTypes = useApi(() => api.taskTypes(), []);
  const questionTypes = useApi(() => api.questionTypes(), []);
  const [rows, setRows] = useState<Draft[]>([blank()]);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  const [postAt, setPostAt] = useState("");

  const patch = (i: number, key: keyof Draft, value: string | boolean) =>
    setRows((rs) => rs.map((r, j) => (i === j ? { ...r, [key]: value } : r)));
  const filled = rows.filter((r) => r.task_type_id);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.createPlan({
        member_id: memberId,
        entry_date: date,
        post_at: postAt || null,
        items: filled.map((r) => ({
          task_type_id: Number(r.task_type_id),
          question_type_id: r.question_type_id ? Number(r.question_type_id) : null,
          customer: r.customer || null,
          count: r.count ? Number(r.count) : null,
          due_at: r.due_at || null,
          notes: r.notes || null,
          create_jira: r.create_jira,
        })),
      });
      onCreated();
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
      {error ? <Banner tone="error">{error.message}</Banner> : null}

      {rows.map((row, i) => (
        <div className="task-row plan-line" key={i}>
          <div>
            <label className="label">What *</label>
            <select className="field" value={row.task_type_id}
                    onChange={(e) => patch(i, "task_type_id", e.target.value)}>
              <option value="">Pick a work type…</option>
              {(taskTypes.data ?? []).map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Question type</label>
            <select className="field" value={row.question_type_id}
                    onChange={(e) => patch(i, "question_type_id", e.target.value)}>
              <option value="">—</option>
              {(questionTypes.data ?? []).map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
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
            <label className="label">Due</label>
            <DateField
              value={row.due_at}
              ariaLabel="Due date"
              onChange={(iso) => patch(i, "due_at", iso)}
            />
          </div>
          <div className="task-row-wide">
            <label className="label">Notes</label>
            <textarea className="field" rows={2} value={row.notes}
                      onChange={(e) => patch(i, "notes", e.target.value)} />
          </div>
          <div className="task-row-wide">
            <label className="check">
              <input type="checkbox" checked={row.create_jira}
                     onChange={(e) => patch(i, "create_jira", e.target.checked)} />
              <span>Raise a Jira ticket for this</span>
            </label>
          </div>
        </div>
      ))}

      {/* Written now, announced later — the 6pm-for-8pm case. */}
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
        <button className="btn btn-primary" disabled={saving || !filled.length} onClick={save}>
          {saving ? "Saving…" : "Start the day"}
        </button>
      </div>
    </>
  );
}

/* ── later: report against it ────────────────────────────────────────────── */

interface Line { status: Status; notes: string; effort_minutes: string; due_at: string }

function DayInProgress({
  plan, date, memberId, onChange,
}: { plan: Entry; date: string; memberId: number; onChange: () => void }) {
  const taskTypes = useApi(() => api.taskTypes(), []);
  const [lines, setLines] = useState<Record<number, Line>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
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

  const lineFor = (item: Item): Line =>
    lines[item.id] ?? {
      status: item.status, notes: "", effort_minutes: "", due_at: item.due_at ?? date,
    };
  const patch = (item: Item, key: keyof Line, value: string) =>
    setLines((l) => ({ ...l, [item.id]: { ...lineFor(item), [key]: value } }));

  const touched = plan.items.filter((i) => {
    const l = lines[i.id];
    return l && (l.notes.trim() || l.effort_minutes || l.status !== i.status);
  });
  const allItems = [...plan.items, ...loggedExtras];
  const done = allItems.filter((i) => i.status === "closed").length;

  async function submit() {
    setError(null);
    setSaving(true);
    try {
      await api.createUpdate({
        member_id: memberId,
        entry_date: date,
        plan_lines: touched.map((i) => {
          const l = lineFor(i);
          return {
            plan_item_id: i.id,
            status: l.status,
            notes: l.notes.trim() || `Moved to ${statusLabel(l.status)}`,
            due_at: l.due_at || date,
            effort_minutes: l.effort_minutes ? Number(l.effort_minutes) : null,
          };
        }),
      });
      setLines({});
      setSaved(true);
      updates.reload();
      onChange();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setSaving(false);
    }
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
        <StatTile label="To report" value={touched.length} />
      </div>

      {error ? <Banner tone="error">{error.message}</Banner> : null}
      {saved ? <Banner tone="info">Update logged.</Banner> : null}

      <SectionHeading
        title="How today's going"
        color="var(--accent-indigo)"
        action={
          <button className="btn btn-secondary" onClick={() => setTicketing(true)}>
            + New ticket
          </button>
        }
      />

      {/* One row per task rather than a card of five labelled fields each. The
          old layout gave a single task the height this gives four, which on the
          screen people open every morning is the difference between seeing the
          day and scrolling through it. Column headers name the inputs, so the
          per-field labels are redundant — each control keeps an aria-label. */}
      <div className="table-scroll day-table">
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Task</th>
              <th>Customer</th>
              <th className="num">Effort (m)</th>
              <th>Due</th>
              <th>What happened</th>
            </tr>
          </thead>
          <tbody>
            {plan.items.map((item) => {
              const l = lineFor(item);
              return (
                <tr key={item.id}>
                  <td>
                    <button className={`pill pill-${item.status} pill-button`}
                            onClick={() => setMoving(item)} title="Move status">
                      {statusLabel(item.status)}
                    </button>
                  </td>
                  <td className="text">
                    <span className="day-task">{item.task_type}</span>
                    {item.jira_issue_key ? (
                      <a className="tag" href={item.jira_issue_url ?? "#"} target="_blank"
                         rel="noreferrer">{item.jira_issue_key}</a>
                    ) : item.jira_state === "pending" ? (
                      <span className="pill pill-muted">syncing…</span>
                    ) : item.jira_state === "failed" ? (
                      <span className="pill pill-blocked" title="Jira ticket creation failed">failed</span>
                    ) : null}
                    <select className="field field-inline" value={l.status}
                            aria-label={`Move ${item.task_type} to`}
                            onChange={(e) => patch(item, "status", e.target.value)}>
                      <option value="open">Open</option>
                      <option value="in_progress">In progress</option>
                      <option value="blocked">Blocked</option>
                      <option value="closed">Done</option>
                    </select>
                  </td>
                  <td>{item.customer ?? <span className="muted">—</span>}</td>
                  <td className="num">
                    {item.status === "closed" ? (
                      mins(item.effort_minutes)
                    ) : (
                      <input className="field field-inline field-num" type="number" min={0} step={5}
                             placeholder="e.g. 30" value={l.effort_minutes}
                             aria-label={`Effort in minutes for ${item.task_type}`}
                             onChange={(e) => patch(item, "effort_minutes", e.target.value)} />
                    )}
                  </td>
                  <td>
                    <DateField
                      className="field field-inline"
                      value={l.due_at}
                      ariaLabel={`Due date for `}
                      onChange={(iso) => patch(item, "due_at", iso)}
                    />
                  </td>
                  <td className="text">
                    <input className="field field-inline" value={l.notes}
                           placeholder="Leave blank to just move the status"
                           aria-label={`What happened with ${item.task_type}`}
                           onChange={(e) => patch(item, "notes", e.target.value)} />
                  </td>
                </tr>
              );
            })}
            {loggedExtras.map((item) => (
              <ExtraRow
                key={item.id}
                item={item}
                onMove={() => setMoving(item)}
                onSaved={() => { onChange(); updates.reload(); }}
              />
            ))}
          </tbody>
        </table>
      </div>

      <div className="btn-row">
        <span className="topbar-spacer" />
        <span className="muted">
          {touched.length} task{touched.length === 1 ? "" : "s"} to report
        </span>
        <button className="btn btn-primary" disabled={saving || !touched.length} onClick={submit}>
          {saving ? "Saving…" : "Log update"}
        </button>
      </div>

      {moving ? (
        <StatusDialog item={moving} onClose={() => setMoving(null)}
                      onSaved={() => { setMoving(null); onChange(); updates.reload(); }} />
      ) : null}

      {ticketing ? (
        <NewTicketDialog
          memberId={memberId}
          date={date}
          taskTypes={taskTypes.data ?? []}
          onClose={() => setTicketing(false)}
          onCreated={() => { onChange(); updates.reload(); }}
        />
      ) : null}
    </>
  );
}

/** A ticket raised outside the plan isn't part of the batched "Log update"
 * submit, so status and effort here save immediately on change rather than
 * being staged — same fields as a planned row, different save path. */
function ExtraRow({
  item, onMove, onSaved,
}: { item: Item; onMove: () => void; onSaved: () => void }) {
  const [effort, setEffort] = useState(item.effort_minutes?.toString() ?? "");
  const [saving, setSaving] = useState(false);

  async function saveStatus(status: string) {
    setSaving(true);
    try {
      await api.patchItem(item.id, { status });
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  async function saveEffort() {
    if (effort === (item.effort_minutes?.toString() ?? "")) return;
    setSaving(true);
    try {
      await api.patchItem(item.id, { effort_minutes: effort === "" ? null : Number(effort) });
      onSaved();
    } catch {
      setEffort(item.effort_minutes?.toString() ?? "");
    } finally {
      setSaving(false);
    }
  }

  return (
    <tr>
      <td>
        <button className={`pill pill-${item.status} pill-button`} onClick={onMove} title="Move status">
          {statusLabel(item.status)}
        </button>
      </td>
      <td className="text">
        <span className="day-task">{item.task_type}</span>
        {item.jira_issue_key ? (
          <a className="tag" href={item.jira_issue_url ?? "#"} target="_blank"
             rel="noreferrer">{item.jira_issue_key}</a>
        ) : item.jira_state === "pending" ? (
          <span className="pill pill-muted">syncing…</span>
        ) : item.jira_state === "failed" ? (
          <span className="pill pill-blocked" title="Jira ticket creation failed">failed</span>
        ) : null}
        <select className="field field-inline" value={item.status} disabled={saving}
                aria-label={`Move ${item.task_type} to`}
                onChange={(e) => saveStatus(e.target.value)}>
          <option value="open">Open</option>
          <option value="in_progress">In progress</option>
          <option value="blocked">Blocked</option>
          <option value="closed">Done</option>
        </select>
      </td>
      <td>{item.customer ?? <span className="muted">—</span>}</td>
      <td className="num">
        {item.status === "closed" ? (
          mins(item.effort_minutes)
        ) : (
          <input className="field field-inline field-num" type="number" min={0} step={5}
                 placeholder="e.g. 30" value={effort} disabled={saving}
                 aria-label={`Effort in minutes for ${item.task_type}`}
                 onChange={(e) => setEffort(e.target.value)}
                 onBlur={saveEffort} />
        )}
      </td>
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
  memberId: number; date: string; taskTypes: Lookup[]; onClose: () => void; onCreated: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const questionTypes = useApi(() => api.questionTypes(), []);
  const [taskTypeId, setTaskTypeId] = useState("");
  const [questionTypeId, setQuestionTypeId] = useState("");
  const [customer, setCustomer] = useState("");
  const [count, setCount] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [notes, setNotes] = useState("");
  // Same default as the morning plan — an unwanted ticket is more annoying to
  // undo than a wanted one is to ask for.
  const [createJira, setCreateJira] = useState(false);
  const [postAt, setPostAt] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  async function create() {
    setError(null);
    setSaving(true);
    try {
      await api.createUpdate({
        member_id: memberId,
        entry_date: date,
        post_at: postAt || null,
        plan_lines: [],
        extra_items: [{
          task_type_id: Number(taskTypeId),
          question_type_id: questionTypeId ? Number(questionTypeId) : null,
          customer: customer || null,
          count: count ? Number(count) : null,
          due_at: dueAt || null,
          notes: notes || null,
          effort_minutes: null,
          create_jira: createJira,
        }],
      });
      onCreated();
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

      <label className="label">What *</label>
      <select className="field" value={taskTypeId} onChange={(e) => setTaskTypeId(e.target.value)}>
        <option value="">Pick a work type…</option>
        {taskTypes.map((t) => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </select>

      <label className="label" style={{ marginTop: 12 }}>Question type</label>
      <select className="field" value={questionTypeId} onChange={(e) => setQuestionTypeId(e.target.value)}>
        <option value="">—</option>
        {(questionTypes.data ?? []).map((t) => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </select>

      <label className="label" style={{ marginTop: 12 }}>Customer</label>
      <input className="field" value={customer} onChange={(e) => setCustomer(e.target.value)} />

      <label className="label" style={{ marginTop: 12 }}>Count</label>
      <input className="field" type="number" min={1} value={count} onChange={(e) => setCount(e.target.value)} />

      <label className="label" style={{ marginTop: 12 }}>Due</label>
      <DateField value={dueAt} ariaLabel="Due date" onChange={setDueAt} />

      <label className="label" style={{ marginTop: 12 }}>Notes</label>
      <textarea className="field" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />

      <label className="check" style={{ marginTop: 12 }}>
        <input type="checkbox" checked={createJira} onChange={(e) => setCreateJira(e.target.checked)} />
        <span>Raise a Jira ticket for this</span>
      </label>

      {/* Same as the morning plan — written now, announced later. */}
      <SchedulePicker value={postAt} onChange={setPostAt} />

      <div className="btn-row">
        <span className="topbar-spacer" />
        <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={saving || !taskTypeId} onClick={create}>
          {saving ? "Creating…" : "Create ticket"}
        </button>
      </div>
    </dialog>
  );
}
