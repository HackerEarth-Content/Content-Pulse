import { useState } from "react";
import { api } from "../api";
import { Async, Banner, BarList, Card, SectionHeading, StatTile } from "../components/ui";
import { num, relativeTime } from "../format";
import { useApi } from "../hooks/useApi";

const PAGE_SIZE = 25;

export function ContentRequests() {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [page, setPage] = useState(1);
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState<string | null>(null);

  const query = { ...filters, page, page_size: PAGE_SIZE };
  const rows = useApi(() => api.contentRequests(query), [JSON.stringify(query)]);
  const facets = useApi(() => api.contentRequestFilters(), []);
  const stats = useApi(() => api.contentRequestStats({}), []);
  const sync = useApi(() => api.syncStatus(), []);

  const cursor = (sync.data ?? []).find((s) => s.key === "content_requests");

  async function resync() {
    setSyncing(true);
    setSyncNote(null);
    try {
      const result = await api.syncContentRequests();
      setSyncNote(result.ok ? `Synced ${result.synced} issues.` : (result.reason ?? "Sync failed."));
      rows.reload();
      stats.reload();
      sync.reload();
    } finally {
      setSyncing(false);
    }
  }

  const set = (key: string, value: string) => {
    setPage(1);
    setFilters((f) => ({ ...f, [key]: value }));
  };
  const pages = rows.data ? Math.max(1, Math.ceil(rows.data.total / PAGE_SIZE)) : 1;

  return (
    <>
      <SectionHeading
        title="Content requests"
        color="var(--accent-magenta)"
        action={
          <span style={{ display: "flex", gap: 6 }}>
            <button className="section-action" disabled={syncing} onClick={resync}>
              {syncing ? "Syncing…" : "Sync from Jira"}
            </button>
            <button className="section-action" onClick={() => api.exportContentRequests(filters)}>
              Excel
            </button>
          </span>
        }
      />

      {syncNote ? <Banner tone={syncNote.startsWith("Synced") ? "info" : "error"}>{syncNote}</Banner> : null}
      {cursor?.status === "auth_failed" ? (
        <Banner tone="warn">
          Jira rejected the API token, so this board hasn't refreshed since{" "}
          {relativeTime(cursor.last_synced_at)}. Scheduled syncing is paused until a working token
          is set — press Sync to retry.
        </Banner>
      ) : null}

      <Async loading={stats.loading} error={stats.error} data={stats.data}>
        {(s) => (
          <>
            <div className="stat-row">
              <StatTile label="Issues" value={num(s.total)} accent="var(--accent-magenta)" />
              <StatTile label="Open backlog" value={num(s.open_backlog)} accent="var(--accent-orange)" />
              <StatTile label="Statuses" value={num(s.by_status.length)} />
              <StatTile label="Assignees" value={num(s.by_assignee.length)} />
              <StatTile label="Last sync" value={relativeTime(cursor?.last_synced_at ?? null)} />
            </div>
            {s.total > 0 ? (
              <div className="grid cols-2" style={{ marginTop: 12 }}>
                <Card title="By status">
                  <BarList items={s.by_status.map((r) => ({ label: r.key, value: r.count }))} />
                </Card>
                <Card title="By assignee">
                  <BarList
                    items={s.by_assignee
                      .slice(0, 10)
                      .map((r) => ({ label: r.key, value: r.count, color: "var(--accent-indigo)" }))}
                  />
                </Card>
              </div>
            ) : null}
          </>
        )}
      </Async>

      <SectionHeading title="Issues" />
      <div className="filter-bar">
        <input
          className="field"
          placeholder="Search summary…"
          onKeyDown={(e) => e.key === "Enter" && set("q", e.currentTarget.value)}
          onBlur={(e) => set("q", e.currentTarget.value)}
          aria-label="Search summary"
        />
        {(
          [
            ["status", "statuses", "Any status"],
            ["assignee", "assignees", "Any assignee"],
            ["priority", "priorities", "Any priority"],
          ] as const
        ).map(([key, facetKey, label]) => (
          <select
            key={key}
            className="field"
            value={filters[key] ?? ""}
            onChange={(e) => set(key, e.target.value)}
            aria-label={label}
          >
            <option value="">{label}</option>
            {(facets.data?.[facetKey] ?? []).map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        ))}
      </div>

      <Async
        loading={rows.loading}
        error={rows.error}
        data={rows.data}
        empty={{
          title: "No issues stored yet",
          hint: "Press Sync from Jira to mirror the board into the dashboard.",
        }}
      >
        {(page_) =>
          page_.items.length === 0 ? (
            <div className="empty">
              <span className="empty-title">No issues stored yet</span>
              Press “Sync from Jira” to mirror the board. A working API token is required.
            </div>
          ) : (
            <>
              <div className="table-scroll">
                <table className="sticky-col">
                  <thead>
                    <tr>
                      <th>Key</th>
                      <th>Summary</th>
                      <th>Status</th>
                      <th>Assignee</th>
                      <th>Priority</th>
                      <th>Created</th>
                      <th>Due</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page_.items.map((r) => (
                      <tr key={r.issue_key}>
                        <td>
                          <a className="tag" href={r.url} target="_blank" rel="noreferrer">
                            {r.issue_key}
                          </a>
                        </td>
                        <td className="strong">{r.summary}</td>
                        <td>
                          <span className="pill pill-muted">{r.status}</span>
                        </td>
                        <td>{r.assignee ?? "—"}</td>
                        <td className="muted">{r.priority ?? "—"}</td>
                        <td className="mono muted">{r.created_at?.slice(0, 10) ?? "—"}</td>
                        <td className="mono muted">{r.due_date ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="btn-row">
                <span className="muted">
                  {page_.total} issues · page {page} of {pages}
                </span>
                <span className="topbar-spacer" />
                <button className="section-action" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  ← Previous
                </button>
                <button className="section-action" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
                  Next →
                </button>
              </div>
            </>
          )
        }
      </Async>
    </>
  );
}
