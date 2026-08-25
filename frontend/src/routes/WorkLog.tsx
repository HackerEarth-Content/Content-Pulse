import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type EntryFilters } from "../api";
import { StatusDialog } from "../components/StatusDialog";
import { Async, SectionHeading } from "../components/ui";
import { dmy, mins, num, statusLabel } from "../format";
import { useApi } from "../hooks/useApi";
import { rangeQuery, type Range } from "../hooks/usePeriod";
import type { CurrentUser, Item, WorkLogRow } from "../types";

const PAGE_SIZE = 50;

const STREAMS = [
  { value: "content_task", label: "Content Tasks" },
  { value: "content_request", label: "Content Requests" },
  { value: "hc_request", label: "HC Request" },
  { value: "ht_request", label: "HT Request" },
  { value: "hc_ht_feasibility", label: "HC/HT Feasibility" },
  { value: "technical_writing", label: "Technical Writing" },
];

/** The dialog edits an Item; a work-log row is the same record flattened. */
const asItem = (r: WorkLogRow): Item => ({
  id: r.id,
  plan_item_id: r.plan_item_id,
  task_type_id: r.task_type_id,
  task_type: r.task_type,
  title: r.title,
  pipeline: r.pipeline,
  work_type: r.pipeline,
  question_types: r.question_types,
  customer: r.customer,
  count: r.count,
  notes: r.notes,
  due_at: r.due_at,
  effort_minutes: r.effort_minutes,
  status: r.status,
  jira_issue_key: r.jira_issue_key,
  jira_issue_url: r.jira_issue_url,
  jira_state: r.jira_state,
  jira_missing: r.jira_missing,
  parent_issue_key: r.parent_issue_key,
  parent_issue_url: r.parent_issue_url,
});

export function WorkLog({ range, me }: { range: Range; me: CurrentUser["member"] }) {
  const isLead = me?.role === "admin" || me?.role === "manager";
  const [params] = useSearchParams();
  const [filters, setFilters] = useState<EntryFilters>(() => {
    const status = params.get("status");
    return status ? { status } : {};
  });
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [moving, setMoving] = useState<Item | null>(null);

  const query: EntryFilters = {
    from: range.from, to: range.to, ...filters, page, page_size: PAGE_SIZE,
  };
  const rows = useApi(() => api.workLog(query), [JSON.stringify(query)]);
  // Non-leads only ever see their own tickets — the roster is pointless to
  // fetch for a filter they can't use.
  const members = useApi(() => (isLead ? api.members() : Promise.resolve([])), [isLead]);
  const taskTypes = useApi(() => api.taskTypes(), []);

  const set = (patch: EntryFilters) => {
    setPage(1);
    setFilters((f) => {
      const next = { ...f, ...patch };
      for (const k of Object.keys(next) as (keyof EntryFilters)[]) {
        if (next[k] === "" || next[k] === undefined) delete next[k];
      }
      return next;
    });
  };
  const active = Object.keys(filters).length;

  async function exportAs(format: "xlsx" | "csv") {
    setBusy(true);
    try {
      await api.exportWorkLog({ from: range.from, to: range.to, ...filters }, format);
    } finally {
      setBusy(false);
    }
  }

  const pages = rows.data ? Math.max(1, Math.ceil(rows.data.total / PAGE_SIZE)) : 1;

  return (
    <>
      <SectionHeading
        title="Work log"
        action={
          <span style={{ display: "flex", gap: 6 }}>
            <button className="section-action" disabled={busy} onClick={() => exportAs("xlsx")}>
              {busy ? "Preparing…" : "Excel"}
            </button>
            <button className="section-action" disabled={busy} onClick={() => exportAs("csv")}>
              CSV
            </button>
          </span>
        }
      />

      <div className="filter-bar">
        <input
          className="field"
          placeholder="Search summary, customer, work type, TCE-…"
          defaultValue={filters.q ?? ""}
          onKeyDown={(e) => e.key === "Enter" && set({ q: e.currentTarget.value })}
          onBlur={(e) => set({ q: e.currentTarget.value })}
          aria-label="Search"
        />
        {isLead ? (
          <select className="field" value={filters.member_id ?? ""} aria-label="Member"
                  onChange={(e) => set({ member_id: e.target.value ? Number(e.target.value) : undefined })}>
            <option value="">Everyone</option>
            {(members.data ?? []).map((m) => (
              <option key={m.id} value={m.id}>{m.display_name}</option>
            ))}
          </select>
        ) : (
          <select className="field" aria-label="Member" disabled value={me?.id ?? ""}>
            <option value={me?.id ?? ""}>{me?.display_name ?? "Me"}</option>
          </select>
        )}
        <select className="field" value={filters.pipeline ?? ""} aria-label="Stream"
                onChange={(e) => set({ pipeline: e.target.value || undefined })}>
          <option value="">All streams</option>
          {STREAMS.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
        <select className="field" value={filters.status ?? ""} aria-label="Status"
                onChange={(e) => set({ status: e.target.value || undefined })}>
          <option value="">Any status</option>
          <option value="open">Open</option>
          <option value="in_progress">In progress</option>
          <option value="blocked">Blocked</option>
          <option value="closed">Done</option>
        </select>
        <select className="field" value={filters.task_type_id ?? ""} aria-label="Work type"
                onChange={(e) => set({ task_type_id: e.target.value ? Number(e.target.value) : undefined })}>
          <option value="">Any work type</option>
          {(taskTypes.data ?? []).map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        <input className="field" placeholder="Customer" defaultValue={filters.customer ?? ""}
               aria-label="Customer"
               onKeyDown={(e) => e.key === "Enter" && set({ customer: e.currentTarget.value })}
               onBlur={(e) => set({ customer: e.currentTarget.value })} />
        {active ? (
          <button className="section-action" onClick={() => (setFilters({}), setPage(1))}>
            Clear {active} filter{active === 1 ? "" : "s"}
          </button>
        ) : null}
      </div>

      <Async loading={rows.loading} error={rows.error} data={rows.data}>
        {(pageData) =>
          pageData.items.length === 0 ? (
            <div className="empty">
              <span className="empty-title">Nothing matches</span>
              Try a wider date range or clear the filters.
            </div>
          ) : (
            <>
              <div className="table-scroll table-scroll--capped">
                <table className="sticky-col">
                  <thead>
                    <tr>
                      <th>Member</th>
                      <th>Date</th>
                      <th>Stream</th>
                      <th>Work type</th>
                      <th>Customer</th>
                      <th className="num">Items</th>
                      <th className="num">Effort</th>
                      <th>Status</th>
                      <th>Due</th>
                      <th>Jira</th>
                      <th>Summary</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pageData.items.map((r) => (
                      <tr key={r.id}>
                        <td className="strong">
                          <Link className="tag" to={`/members/${r.member_id}?${rangeQuery(range)}`}>
                            {r.member}
                          </Link>
                        </td>
                        <td className="mono">{dmy(r.entry_date)}</td>
                        <td>
                          <span className="pill pill-muted">
                            {r.external_issue_type ?? (r.kind === "plan" ? "Plan" : "Update")}
                          </span>
                        </td>
                        <td>{r.task_type}</td>
                        <td className="muted">{r.customer ?? "—"}</td>
                        <td className="num">{num(r.count)}</td>
                        <td className="num">{mins(r.effort_minutes)}</td>
                        <td>
                          <button className={`pill pill-${r.status} pill-button`}
                                  onClick={() => setMoving(asItem(r))} title="Move status">
                            {statusLabel(r.status)}
                          </button>
                        </td>
                        <td className="mono muted">{r.due_at ?? "—"}</td>
                        <td>
                          {r.jira_issue_key && r.jira_missing ? (
                            <span className="pill pill-blocked" title="No longer found in Jira — it was deleted there">
                              {r.jira_issue_key} removed
                            </span>
                          ) : r.jira_issue_key ? (
                            <a className="tag" href={r.jira_issue_url ?? "#"} target="_blank"
                               rel="noreferrer">{r.jira_issue_key}</a>
                          ) : r.jira_state === "pending" ? (
                            <span className="pill pill-muted">syncing…</span>
                          ) : r.jira_state === "failed" ? (
                            <span className="pill pill-blocked">failed</span>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td className="cell-notes">
                          {r.notes ?? "—"}
                          {r.parent_issue_key ? (
                            <a className="tag" href={r.parent_issue_url ?? "#"} target="_blank"
                               rel="noreferrer" title="Parent ticket" style={{ marginLeft: 6 }}>
                              ↑ {r.parent_issue_key}
                            </a>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="btn-row">
                <span className="muted">
                  {pageData.total.toLocaleString()}{" "}
                  {pageData.total === 1 ? "ticket" : "tickets"} · page {page} of {pages}
                </span>
                <span className="topbar-spacer" />
                <button className="section-action" disabled={page <= 1}
                        onClick={() => setPage((p) => p - 1)}>← Previous</button>
                <button className="section-action" disabled={page >= pages}
                        onClick={() => setPage((p) => p + 1)}>Next →</button>
              </div>
            </>
          )
        }
      </Async>

      {moving ? (
        <StatusDialog item={moving} onClose={() => setMoving(null)} onSaved={rows.reload}
                      canDelete={me?.role === "admin"} />
      ) : null}
    </>
  );
}
