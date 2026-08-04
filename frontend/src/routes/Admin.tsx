import { useState } from "react";
import { ApiError, api } from "../api";
import { Async, Banner, Card, SectionHeading } from "../components/ui";
import { relativeTime } from "../format";
import { useApi } from "../hooks/useApi";
import type { Lookup } from "../types";

type LookupKind = "task-types" | "question-types";

function LookupEditor({ kind, title, sub }: { kind: LookupKind; title: string; sub: string }) {
  const list = useApi(() => api.lookups(kind, true), [kind]);
  const [name, setName] = useState("");
  const [error, setError] = useState<ApiError | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      list.reload();
    } catch (e) {
      setError(e as ApiError);
    }
  }

  const retire = (row: Lookup) =>
    run(() => api.patchLookup(kind, row.id, { is_active: !row.is_active }));

  return (
    <Card title={title} sub={sub}>
      {error ? <Banner tone="error">{error.message}</Banner> : null}

      <div className="filter-bar" style={{ marginBottom: 8 }}>
        <input
          className="field"
          placeholder="Add a value…"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && name.trim()) {
              run(() => api.createLookup(kind, { name: name.trim() }));
              setName("");
            }
          }}
        />
        <button
          className="btn btn-secondary"
          disabled={!name.trim()}
          onClick={() => {
            run(() => api.createLookup(kind, { name: name.trim() }));
            setName("");
          }}
        >
          Add
        </button>
      </div>

      <Async loading={list.loading} error={list.error} data={list.data} empty={{ title: "None yet" }}>
        {(rows) => (
          <div>
            {rows.map((row) => (
              <div className="admin-row" key={row.id}>
                <span className={row.is_active ? "" : "retired"}>{row.name}</span>
                <span className="muted">{row.is_active ? "" : "retired"}</span>
                <button className="section-action" onClick={() => retire(row)}>
                  {row.is_active ? "Retire" : "Restore"}
                </button>
              </div>
            ))}
          </div>
        )}
      </Async>
      <p className="hint">
        Retiring hides a value from forms but leaves every task already using it intact.
      </p>
    </Card>
  );
}

function MemberEditor() {
  const list = useApi(() => api.members({ is_active: undefined }), []);
  const [error, setError] = useState<ApiError | null>(null);
  const [draft, setDraft] = useState<Record<number, { email: string; role: string }>>({});

  async function save(id: number) {
    setError(null);
    try {
      await api.patchMember(id, {
        email: draft[id]?.email?.trim() || null,
        ...(draft[id]?.role ? { role: draft[id].role } : {}),
      });
      setDraft((d) => {
        const { [id]: _, ...rest } = d;
        return rest;
      });
      list.reload();
    } catch (e) {
      setError(e as ApiError);
    }
  }

  return (
    <Card title="Members" sub="an email links a person to their Google account at sign-in">
      {error ? <Banner tone="error">{error.message}</Banner> : null}
      <Async loading={list.loading} error={list.error} data={list.data}>
        {(rows) => (
          <div className="table-scroll" style={{ border: 0, boxShadow: "none" }}>
            <table>
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Active</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((m) => {
                  const edited = draft[m.id];
                  return (
                    <tr key={m.id}>
                      <td className="strong">{m.display_name}</td>
                      <td>
                        <input
                          className="field"
                          type="email"
                          placeholder="name@hackerearth.com"
                          value={edited?.email ?? m.email ?? ""}
                          onChange={(e) =>
                            setDraft((d) => ({
                              ...d,
                              [m.id]: { role: d[m.id]?.role ?? m.role, email: e.target.value },
                            }))
                          }
                        />
                      </td>
                      <td>
                        <select
                          className="field"
                          value={edited?.role ?? m.role}
                          onChange={(e) =>
                            setDraft((d) => ({
                              ...d,
                              [m.id]: { email: d[m.id]?.email ?? m.email ?? "", role: e.target.value },
                            }))
                          }
                        >
                          {["content", "ae", "manager", "admin"].map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        {m.is_active ? (
                          <span className="pill pill-closed">Active</span>
                        ) : (
                          <span className="pill pill-muted">Inactive</span>
                        )}
                      </td>
                      <td>
                        <button
                          className="section-action"
                          disabled={!edited}
                          onClick={() => save(m.id)}
                        >
                          Save
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Async>
    </Card>
  );
}

function Integrations() {
  const sync = useApi(() => api.syncStatus(), []);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState("");

  async function act(label: string, fn: () => Promise<{ [k: string]: unknown }>) {
    setBusy(label);
    setNote(null);
    try {
      const result = await fn();
      setNote(JSON.stringify(result));
      sync.reload();
    } catch (e) {
      setNote((e as ApiError).message);
    } finally {
      setBusy("");
    }
  }

  return (
    <Card title="Integrations" sub="Jira and Slack">
      {note ? <Banner tone="info">{note}</Banner> : null}

      <Async loading={sync.loading} error={sync.error} data={sync.data} empty={{ title: "Never synced" }}>
        {(rows) => (
          <div>
            {rows.map((r) => (
              <div className="admin-row" key={r.key}>
                <span>
                  <strong>{r.key}</strong>{" "}
                  <span className="muted">{relativeTime(r.last_synced_at)}</span>
                  {r.error ? <div className="hint">{r.error}</div> : null}
                </span>
                <span
                  className={`pill ${r.status === "ok" ? "pill-closed" : r.status === "auth_failed" ? "pill-blocked" : "pill-muted"}`}
                >
                  {r.status ?? "unknown"}
                </span>
                <span />
              </div>
            ))}
          </div>
        )}
      </Async>

      <div className="btn-row">
        <button
          className="section-action"
          disabled={!!busy}
          onClick={() => act("jira", () => api.jiraHealth())}
        >
          {busy === "jira" ? "Checking…" : "Check Jira credentials"}
        </button>
        <button
          className="section-action"
          disabled={!!busy}
          onClick={() => act("sync", () => api.syncContentRequests())}
        >
          {busy === "sync" ? "Syncing…" : "Sync content requests"}
        </button>
        <button
          className="section-action"
          disabled={!!busy}
          onClick={() => act("retry", () => api.retryPendingJira())}
        >
          {busy === "retry" ? "Retrying…" : "Retry stuck Jira writes"}
        </button>
      </div>

      <div className="btn-row">
        {(["plan", "update"] as const).map((kind) => (
          <button
            key={kind}
            className="section-action"
            disabled={!!busy}
            onClick={() => act(kind, () => api.slackDigest(kind, true))}
          >
            Preview today's {kind} digest
          </button>
        ))}
        {(["plan", "update"] as const).map((kind) => (
          <button
            key={`post-${kind}`}
            className="btn btn-secondary"
            disabled={!!busy}
            onClick={() =>
              confirm(`Post today's ${kind} digest to Slack? This is visible to the channel.`) &&
              act(kind, () => api.slackDigest(kind, false))
            }
          >
            Post {kind} digest
          </button>
        ))}
      </div>
      <p className="hint">
        Preview renders the message without sending. Posting is visible to everyone in the channel.
      </p>
    </Card>
  );
}

export function Admin() {
  return (
    <>
      <SectionHeading title="Admin" color="var(--accent-orange)" />
      <MemberEditor />
      <div className="grid cols-2" style={{ marginTop: 12 }}>
        <LookupEditor kind="task-types" title="Work types" sub="offered on plan and update forms" />
        <LookupEditor
          kind="question-types"
          title="Question types"
          sub="optional tag on each task"
        />
      </div>
      <div style={{ marginTop: 12 }}>
        <Integrations />
      </div>
    </>
  );
}
