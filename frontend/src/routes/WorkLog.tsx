import { useState } from "react";
import { api, type EntryFilters } from "../api";
import { StatusDialog } from "../components/StatusDialog";
import { Async, KindPill, SectionHeading, StatusPill } from "../components/ui";
import type { Item } from "../types";
import { num, statusLabel } from "../format";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";

const PAGE_SIZE = 50;

export function WorkLog({ range }: { range: Range }) {
  const [filters, setFilters] = useState<EntryFilters>({});
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [moving, setMoving] = useState<Item | null>(null);

  const query: EntryFilters = { from: range.from, to: range.to, ...filters, page, page_size: PAGE_SIZE };
  const key = JSON.stringify(query);
  const entries = useApi(() => api.entries(query), [key]);
  const members = useApi(() => api.members(), []);
  const taskTypes = useApi(() => api.taskTypes(), []);

  const set = (patch: EntryFilters) => {
    setPage(1);
    setFilters((f) => ({ ...f, ...patch }));
  };

  async function exportAs(format: "xlsx" | "csv") {
    setBusy(true);
    try {
      await api.exportWorkLog({ from: range.from, to: range.to, ...filters }, format);
    } finally {
      setBusy(false);
    }
  }

  const pages = entries.data ? Math.ceil(entries.data.total / PAGE_SIZE) : 1;

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
          placeholder="Search notes, customer, work type…"
          defaultValue={filters.q ?? ""}
          onKeyDown={(e) => e.key === "Enter" && set({ q: e.currentTarget.value })}
          onBlur={(e) => set({ q: e.currentTarget.value })}
          aria-label="Search"
        />
        <select
          className="field"
          value={filters.member_id ?? ""}
          onChange={(e) => set({ member_id: e.target.value ? Number(e.target.value) : undefined })}
          aria-label="Member"
        >
          <option value="">All members</option>
          {(members.data ?? []).map((m) => (
            <option key={m.id} value={m.id}>
              {m.display_name}
            </option>
          ))}
        </select>
        <select
          className="field"
          value={filters.kind ?? ""}
          onChange={(e) => set({ kind: e.target.value || undefined })}
          aria-label="Kind"
        >
          <option value="">Plans & updates</option>
          <option value="plan">Plans</option>
          <option value="update">Updates</option>
        </select>
        <select
          className="field"
          value={filters.status ?? ""}
          onChange={(e) => set({ status: e.target.value || undefined })}
          aria-label="Status"
        >
          <option value="">Any status</option>
          <option value="open">Open</option>
          <option value="in_progress">In progress</option>
          <option value="blocked">Blocked</option>
          <option value="closed">Done</option>
        </select>
        <select
          className="field"
          value={filters.task_type_id ?? ""}
          onChange={(e) => set({ task_type_id: e.target.value ? Number(e.target.value) : undefined })}
          aria-label="Work type"
        >
          <option value="">Any work type</option>
          {(taskTypes.data ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
        {Object.values(filters).some(Boolean) ? (
          <button className="section-action" onClick={() => (setFilters({}), setPage(1))}>
            Clear
          </button>
        ) : null}
      </div>

      <Async
        loading={entries.loading}
        error={entries.error}
        data={entries.data}
        empty={{ title: "No entries", hint: "Try a wider date range or clear the filters." }}
      >
        {(pageData) =>
          pageData.items.length === 0 ? (
            <div className="empty">
              <span className="empty-title">No entries match</span>
              Try a wider date range or clear the filters.
            </div>
          ) : (
            <>
              <div className="table-scroll">
                <table className="sticky-col">
                  <thead>
                    <tr>
                      <th>Member</th>
                      <th>Date</th>
                      <th>Kind</th>
                      <th>Work type</th>
                      <th>Question type</th>
                      <th>Customer</th>
                      <th className="num">Count</th>
                      <th>Status</th>
                      <th>Due</th>
                      <th>Jira</th>
                      <th>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pageData.items.flatMap((entry) =>
                      entry.items.length === 0
                        ? [
                            <tr key={`e${entry.id}`}>
                              <td className="strong">{entry.member}</td>
                              <td className="mono">{entry.entry_date}</td>
                              <td>
                                <KindPill kind={entry.kind} />
                              </td>
                              <td colSpan={7} className="muted">
                                No tasks logged
                              </td>
                              <td className="cell-notes">{entry.raw_text ?? "—"}</td>
                            </tr>,
                          ]
                        : entry.items.map((item) => (
                            <tr key={item.id}>
                              <td className="strong">{entry.member}</td>
                              <td className="mono">{entry.entry_date}</td>
                              <td>
                                <KindPill kind={entry.kind} />
                              </td>
                              <td>{item.task_type}</td>
                              <td className="muted">{item.question_type ?? "—"}</td>
                              <td>{item.customer ?? "—"}</td>
                              <td className="num">{num(item.count)}</td>
                              <td>
                                {entry.kind === "update" && item.plan_item_id === null ? (
                                  <StatusPill status={item.status} />
                                ) : (
                                  <button
                                    className={`pill pill-${item.status} pill-button`}
                                    onClick={() => setMoving(item)}
                                    title="Move status"
                                  >
                                    {statusLabel(item.status)}
                                  </button>
                                )}
                              </td>
                              <td className="mono muted">{item.due_at ?? "—"}</td>
                              <td>
                                {item.jira_issue_key ? (
                                  <a
                                    className="tag"
                                    href={item.jira_issue_url ?? "#"}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    {item.jira_issue_key}
                                  </a>
                                ) : item.jira_state === "pending" ? (
                                  <span className="pill pill-muted">syncing…</span>
                                ) : item.jira_state === "failed" ? (
                                  <span className="pill pill-blocked">failed</span>
                                ) : (
                                  <span className="muted">—</span>
                                )}
                              </td>
                              <td className="cell-notes">{item.notes ?? "—"}</td>
                            </tr>
                          ))
                    )}
                  </tbody>
                </table>
              </div>

              <div className="btn-row">
                <span className="muted">
                  {pageData.total} {pageData.total === 1 ? "entry" : "entries"} · page {page} of{" "}
                  {pages}
                </span>
                <span className="topbar-spacer" />
                <button
                  className="section-action"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  ← Previous
                </button>
                <button
                  className="section-action"
                  disabled={page >= pages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next →
                </button>
              </div>
            </>
          )
        }
      </Async>

      {moving ? (
        <StatusDialog item={moving} onClose={() => setMoving(null)} onSaved={entries.reload} />
      ) : null}
    </>
  );
}
