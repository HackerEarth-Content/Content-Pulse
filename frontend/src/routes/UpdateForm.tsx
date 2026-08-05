import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api";
import { Banner, Card, SectionHeading, Skeleton, StatusPill } from "../components/ui";
import { today } from "../format";
import { useApi } from "../hooks/useApi";
import type { CurrentUser, Entry, Status } from "../types";

interface Line {
  plan_item_id: number;
  status: Status;
  count: string;
  notes: string;
  due_at: string;
}

interface Extra {
  task_type_id: string;
  question_type_id: string;
  customer: string;
  count: string;
  notes: string;
}

const blankExtra = (): Extra => ({
  task_type_id: "",
  question_type_id: "",
  customer: "",
  count: "",
  notes: "",
});

export function UpdateForm({ me }: { me: CurrentUser["member"] }) {
  const navigate = useNavigate();
  const members = useApi(() => api.members(), []);
  const taskTypes = useApi(() => api.taskTypes(), []);
  const questionTypes = useApi(() => api.questionTypes(), []);

  // Managers and admins file on anyone's behalf; everyone else files as
  // themselves, so the field becomes a label rather than a choice.
  const canFileForOthers = !me || me.role === "admin" || me.role === "manager";
  const [memberId, setMemberId] = useState(me ? String(me.id) : "");
  const [date, setDate] = useState(today());
  const [plan, setPlan] = useState<Entry | null>(null);
  const [planState, setPlanState] = useState<"idle" | "loading" | "none" | "ready">("idle");
  const [lines, setLines] = useState<Line[]>([]);
  const [extras, setExtras] = useState<Extra[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  // Refetch the plan whenever member or date changes — the whole point of the
  // update form is that it's prefilled from what was planned.
  useEffect(() => {
    if (!memberId || !date) {
      setPlanState("idle");
      setPlan(null);
      setLines([]);
      return;
    }
    let cancelled = false;
    setPlanState("loading");
    api
      .planFor(Number(memberId), date)
      .then((p) => {
        if (cancelled) return;
        setPlan(p);
        setLines(
          p.items.map((i) => ({
            plan_item_id: i.id,
            status: i.status,
            count: i.count?.toString() ?? "",
            notes: "",
            due_at: i.due_at ?? date,
          }))
        );
        setPlanState("ready");
      })
      .catch((e: ApiError) => {
        if (cancelled) return;
        setPlan(null);
        setLines([]);
        setPlanState(e.code === "no_plan" ? "none" : "idle");
        if (e.code !== "no_plan") setError(e);
      });
    return () => {
      cancelled = true;
    };
  }, [memberId, date]);

  const patchLine = (i: number, key: keyof Line, value: string) =>
    setLines((ls) => ls.map((l, j) => (i === j ? { ...l, [key]: value } : l)));
  const patchExtra = (i: number, key: keyof Extra, value: string) =>
    setExtras((es) => es.map((e, j) => (i === j ? { ...e, [key]: value } : e)));

  const readyLines = lines.filter((l) => l.notes.trim() && l.due_at);
  const readyExtras = extras.filter((e) => e.task_type_id);
  const canSave = Boolean(memberId) && readyLines.length + readyExtras.length > 0;

  async function submit() {
    setError(null);
    setSaving(true);
    try {
      const entry = await api.createUpdate({
        member_id: Number(memberId),
        entry_date: date,
        plan_lines: readyLines.map((l) => ({
          plan_item_id: l.plan_item_id,
          status: l.status,
          count: l.count ? Number(l.count) : null,
          notes: l.notes.trim(),
          due_at: l.due_at,
        })),
        extra_items: readyExtras.map((e) => ({
          task_type_id: Number(e.task_type_id),
          question_type_id: e.question_type_id ? Number(e.question_type_id) : null,
          customer: e.customer || null,
          count: e.count ? Number(e.count) : null,
          notes: e.notes || null,
        })),
      });
      navigate(`/work-log?from=${entry.entry_date}&to=${entry.entry_date}`);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <SectionHeading title="Daily update" color="var(--accent-aqua)" />

      {error ? (
        <Banner tone="error">
          {error.message}
          {error.code === "plan_item_mismatch" ? " Reload the page to pick up the current plan." : ""}
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
      </Card>

      <SectionHeading title="Progress on the plan" color="var(--accent-indigo)" />

      {planState === "loading" && <Skeleton rows={2} height={72} />}

      {planState === "idle" && (
        <div className="empty">
          <span className="empty-title">Pick a member and date</span>
          Their plan for that day loads here.
        </div>
      )}

      {planState === "none" && (
        <Banner tone="info">
          No plan exists for this member and date. Log what they did as extra work below.
        </Banner>
      )}

      {planState === "ready" &&
        plan?.items.map((item, i) => (
          <div className="task-row plan-line" key={item.id}>
            <div className="task-row-wide">
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                <strong>{item.task_type}</strong>
                {item.customer ? <span className="pill pill-muted">{item.customer}</span> : null}
                {item.question_type ? (
                  <span className="pill pill-muted">{item.question_type}</span>
                ) : null}
                <StatusPill status={item.status} />
                {item.jira_issue_key ? (
                  <a className="tag" href={item.jira_issue_url ?? "#"} target="_blank" rel="noreferrer">
                    {item.jira_issue_key}
                  </a>
                ) : null}
              </div>
            </div>
            <div>
              <label className="label">Status</label>
              <select
                className="field"
                value={lines[i]?.status ?? "open"}
                onChange={(e) => patchLine(i, "status", e.target.value)}
              >
                <option value="open">Open</option>
                <option value="in_progress">In progress</option>
                <option value="blocked">Blocked</option>
                <option value="closed">Done</option>
              </select>
            </div>
            <div>
              <label className="label" title="How many items this task produces — questions, docs, reviews">
              Count
            </label>
              <input
                className="field"
                type="number"
                min={1}
                value={lines[i]?.count ?? ""}
                onChange={(e) => patchLine(i, "count", e.target.value)}
              />
            </div>
            <div>
              <label className="label">Due</label>
              <input
                className="field"
                type="date"
                value={lines[i]?.due_at ?? date}
                onChange={(e) => patchLine(i, "due_at", e.target.value)}
              />
            </div>
            <div className="task-row-wide">
              <label className="label">Progress / blockers — required</label>
              <textarea
                className="field"
                rows={2}
                value={lines[i]?.notes ?? ""}
                onChange={(e) => patchLine(i, "notes", e.target.value)}
                placeholder="What moved today?"
              />
            </div>
          </div>
        ))}

      <SectionHeading title="Extra work" color="var(--accent-aqua)" />
      <p className="hint" style={{ marginTop: -6, marginBottom: 10 }}>
        Anything done that wasn't planned. These are recorded as done.
      </p>

      {extras.map((row, i) => (
        <div className="task-row extra-line" key={i}>
          <div>
            <label className="label">Work type</label>
            <select
              className="field"
              value={row.task_type_id}
              onChange={(e) => patchExtra(i, "task_type_id", e.target.value)}
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
              onChange={(e) => patchExtra(i, "question_type_id", e.target.value)}
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
              onChange={(e) => patchExtra(i, "customer", e.target.value)}
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
              onChange={(e) => patchExtra(i, "count", e.target.value)}
            />
          </div>
          <div />
          <div className="task-row-wide">
            <label className="label">Notes</label>
            <textarea
              className="field"
              rows={2}
              value={row.notes}
              onChange={(e) => patchExtra(i, "notes", e.target.value)}
            />
          </div>
        </div>
      ))}

      <div className="btn-row">
        <button className="btn btn-secondary" onClick={() => setExtras((e) => [...e, blankExtra()])}>
          + Add extra work
        </button>
        <span className="topbar-spacer" />
        <span className="muted">
          {readyLines.length} of {lines.length} plan tasks · {readyExtras.length} extra
        </span>
        <button className="btn btn-primary" disabled={saving || !canSave} onClick={submit}>
          {saving ? "Saving…" : "Save update"}
        </button>
      </div>
      {lines.length > 0 && readyLines.length < lines.length ? (
        <p className="hint">Plan tasks need a note and a due date before they can be submitted.</p>
      ) : null}
    </>
  );
}
