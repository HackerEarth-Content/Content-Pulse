import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api";
import { Banner, Card, SectionHeading } from "../components/ui";
import type { CurrentUser, Entry } from "../types";
import { today } from "../format";
import { useApi } from "../hooks/useApi";

interface Draft {
  task_type_id: string;
  question_type_id: string;
  customer: string;
  count: string;
  due_at: string;
  notes: string;
}

const blank = (): Draft => ({
  task_type_id: "",
  question_type_id: "",
  customer: "",
  count: "",
  due_at: "",
  notes: "",
});

export function PlanForm({ me }: { me: CurrentUser["member"] }) {
  const navigate = useNavigate();
  const members = useApi(() => api.members(), []);
  const taskTypes = useApi(() => api.taskTypes(), []);
  const questionTypes = useApi(() => api.questionTypes(), []);

  // Managers and admins file on anyone's behalf; everyone else files as
  // themselves, so the field becomes a label rather than a choice.
  const canFileForOthers = !me || me.role === "admin" || me.role === "manager";
  const [memberId, setMemberId] = useState(me ? String(me.id) : "");
  const [date, setDate] = useState(today());
  const [rawText, setRawText] = useState("");
  const [rows, setRows] = useState<Draft[]>([blank(), blank()]);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<Entry | null>(null);
  const [tickets, setTickets] = useState<{ key: string | null; state: string }[]>([]);

  // Jira issues are created after the response is sent, so poll until every
  // item has settled rather than making the user reload to see ticket keys.
  useEffect(() => {
    if (!saved) return;
    let stop = false;
    const tick = async () => {
      const state = await api.jiraState(saved.id).catch(() => null);
      if (stop || !state) return;
      setTickets(state.items.map((i) => ({ key: i.jira_issue_key, state: i.jira_state })));
      if (state.pending) setTimeout(tick, 1500);
    };
    tick();
    return () => {
      stop = true;
    };
  }, [saved]);

  const patch = (i: number, key: keyof Draft, value: string) =>
    setRows((rs) => rs.map((r, j) => (i === j ? { ...r, [key]: value } : r)));

  const filled = rows.filter((r) => r.task_type_id);

  async function submit() {
    setError(null);
    setSaving(true);
    try {
      const entry = await api.createPlan({
        member_id: Number(memberId),
        entry_date: date,
        raw_text: rawText || null,
        items: filled.map((r) => ({
          task_type_id: Number(r.task_type_id),
          question_type_id: r.question_type_id ? Number(r.question_type_id) : null,
          customer: r.customer || null,
          count: r.count ? Number(r.count) : null,
          due_at: r.due_at || null,
          notes: r.notes || null,
        })),
      });
      setSaved(entry);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setSaving(false);
    }
  }

  if (saved) {
    const pending = tickets.filter((t) => t.state === "pending").length;
    const failed = tickets.filter((t) => t.state === "failed").length;
    return (
      <>
        <SectionHeading title="Plan saved" color="var(--accent-aqua)" />
        <Card
          title={`${saved.items.length} ${saved.items.length === 1 ? "task" : "tasks"} logged for ${saved.member}`}
          sub={saved.entry_date}
        >
          {pending > 0 ? (
            <Banner tone="info">Creating {pending} Jira {pending === 1 ? "ticket" : "tickets"}…</Banner>
          ) : failed > 0 ? (
            <Banner tone="warn">
              {failed} Jira {failed === 1 ? "ticket" : "tickets"} failed. The tasks are saved — retry
              from Admin once the API token works.
            </Banner>
          ) : null}
          <div className="bar-list">
            {saved.items.map((item, i) => (
              <div key={item.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{ flex: 1 }}>{item.task_type}</span>
                {tickets[i]?.key ? (
                  <span className="tag">{tickets[i].key}</span>
                ) : tickets[i]?.state === "failed" ? (
                  <span className="pill pill-blocked">Jira failed</span>
                ) : (
                  <span className="pill pill-muted">syncing…</span>
                )}
              </div>
            ))}
          </div>
          <div className="btn-row">
            <button
              className="btn btn-secondary"
              onClick={() => {
                setSaved(null);
                setTickets([]);
                setRows([blank(), blank()]);
              }}
            >
              Log another plan
            </button>
            <button
              className="btn btn-primary"
              onClick={() => navigate(`/work-log?from=${saved.entry_date}&to=${saved.entry_date}`)}
            >
              View in work log
            </button>
          </div>
        </Card>
      </>
    );
  }

  return (
    <>
      <SectionHeading title="New plan" color="var(--accent-indigo)" />

      {error ? (
        <Banner tone={error.code === "plan_exists" ? "warn" : "error"}>
          {error.message}
          {error.code === "plan_exists" ? (
            <>
              {" "}
              <a
                className="tag"
                href={`/work-log?from=${date}&to=${date}`}
                onClick={(e) => {
                  e.preventDefault();
                  navigate(`/work-log?from=${date}&to=${date}`);
                }}
              >
                View it
              </a>
            </>
          ) : null}
        </Banner>
      ) : null}

      <Card title="Who and when">
        <div className="field-row">
          <div>
            <label className="label" htmlFor="member">
              {canFileForOthers ? "Member" : "Filing as"}
            </label>
            {canFileForOthers ? (
              <select
                id="member"
                className="field"
                value={memberId}
                onChange={(e) => setMemberId(e.target.value)}
              >
                <option value="">Select a member…</option>
                {(members.data ?? []).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name}
                  </option>
                ))}
              </select>
            ) : (
              <div className="field field-static">
                <strong>{me!.display_name}</strong>
                <span className="pill pill-muted">{me!.role}</span>
              </div>
            )}
          </div>
          <div>
            <label className="label" htmlFor="date">
              Date
            </label>
            <input
              id="date"
              className="field"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          <label className="label" htmlFor="raw">
            Summary (optional)
          </label>
          <textarea
            id="raw"
            className="field"
            rows={2}
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            placeholder="Anything that doesn't fit a task row"
          />
        </div>
      </Card>

      <SectionHeading title="Planned tasks" />
      {rows.map((row, i) => (
        <div className="task-row plan-line" key={i}>
          <div>
            <label className="label">Work type</label>
            <select
              className="field"
              value={row.task_type_id}
              onChange={(e) => patch(i, "task_type_id", e.target.value)}
            >
              <option value="">Select…</option>
              {(taskTypes.data ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Question type</label>
            <select
              className="field"
              value={row.question_type_id}
              onChange={(e) => patch(i, "question_type_id", e.target.value)}
            >
              <option value="">—</option>
              {(questionTypes.data ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Customer</label>
            <input
              className="field"
              value={row.customer}
              onChange={(e) => patch(i, "customer", e.target.value)}
              placeholder="e.g. CleverTap"
            />
          </div>
          <div>
            <label className="label" title="How many items this task produces — questions, docs, reviews">
              Count
            </label>
            <input
              className="field"
              type="number"
              min={1}
              value={row.count}
              onChange={(e) => patch(i, "count", e.target.value)}
            />
          </div>
          <div>
            <label className="label">Due</label>
            <input
              className="field"
              type="date"
              value={row.due_at}
              onChange={(e) => patch(i, "due_at", e.target.value)}
            />
          </div>
          <div className="task-row-wide">
            <label className="label">Notes</label>
            <textarea
              className="field"
              rows={2}
              value={row.notes}
              onChange={(e) => patch(i, "notes", e.target.value)}
            />
          </div>
        </div>
      ))}

      <div className="btn-row">
        <button className="btn btn-secondary" onClick={() => setRows((r) => [...r, blank()])}>
          + Add task
        </button>
        {rows.length > 1 ? (
          <button className="btn btn-secondary" onClick={() => setRows((r) => r.slice(0, -1))}>
            Remove last
          </button>
        ) : null}
        <span className="topbar-spacer" />
        <span className="muted">
          {filled.length} {filled.length === 1 ? "task" : "tasks"} ready
        </span>
        <button
          className="btn btn-primary"
          disabled={saving || !memberId || filled.length === 0}
          onClick={submit}
        >
          {saving ? "Saving…" : "Save plan"}
        </button>
      </div>
      <p className="hint">
        Jira tickets are created in the background — the plan saves immediately and ticket keys
        appear in the work log shortly after.
      </p>
    </>
  );
}
