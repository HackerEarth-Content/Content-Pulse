import { useState } from "react";
import { ApiError, api } from "../api";
import { Async, Banner, Card, SectionHeading } from "../components/ui";
import { relativeTime } from "../format";
import { useApi } from "../hooks/useApi";
import type { Lookup } from "../types";

type LookupKind = "task-types" | "question-types";

/** The values currently in use. They come from Jira — the backfill creates any
 * it meets — so there is nothing to add here by hand. Retiring one takes it off
 * this list and out of the forms; the tickets already using it are untouched. */
function LookupList({ kind, title, sub }: { kind: LookupKind; title: string; sub: string }) {
  const active = useApi(() => api.lookups(kind, false), [kind]);
  // Only to say how many are hidden — retired values are never listed.
  const all = useApi(() => api.lookups(kind, true), [kind]);
  const list = active;
  const retired = (all.data?.length ?? 0) - (active.data?.length ?? 0);
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

      <Async loading={list.loading} error={list.error} data={list.data}
             empty={{ title: "None in use yet" }}>
        {(rows) => (
          <div>
            {rows.map((row) => (
              <div className="admin-row" key={row.id}>
                <span>{row.name}</span>
                <span />
                <button className="section-action" onClick={() => retire(row)}
                        title="Take this off the list and out of the forms">
                  Retire
                </button>
              </div>
            ))}
          </div>
        )}
      </Async>
      <p className="hint">
        {list.data?.length ?? 0} in use, synced from Jira as the backfill meets them.
        {retired > 0
          ? ` ${retired} retired and hidden — their tickets still read correctly.`
          : ""}
      </p>
    </Card>
  );
}

const ROLES = ["content", "ae", "manager", "admin"];

// Slack's own format for a member id — never a username or display name,
// both of which look plausible and silently never ping anyone.
const SLACK_ID_RE = /^[UW][A-Z0-9]{6,}$/;

function invalidSlackId(value: string): ApiError | null {
  return value && !SLACK_ID_RE.test(value)
    ? new ApiError(0, "invalid_slack_id",
        "That doesn't look like a Slack member id. It should look like U0123ABCD — " +
          "copy it from their Slack profile's \"Copy member ID\", not their name.")
    : null;
}

function MemberEditor() {
  const list = useApi(() => api.members({ is_active: undefined }), []);
  const [error, setError] = useState<ApiError | null>(null);
  const [draft, setDraft] = useState<
    Record<number, { email: string; role: string; slack_user_id: string }>
  >({});
  const [adding, setAdding] = useState({
    display_name: "", email: "", role: "content", slack_user_id: "",
  });
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function add() {
    setError(null);
    const slackId = adding.slack_user_id.trim();
    const invalid = invalidSlackId(slackId);
    if (invalid) return setError(invalid);
    setBusy(true);
    try {
      await api.createMember({
        display_name: adding.display_name.trim(),
        email: adding.email.trim() || null,
        role: adding.role,
        slack_user_id: slackId || null,
      });
      setAdding({ display_name: "", email: "", role: "content", slack_user_id: "" });
      list.reload();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  async function remove(m: { id: number; display_name: string }) {
    const ok = confirm(
      `Remove ${m.display_name}?\n\n` +
        "If they never logged any work they're deleted outright. If they did, " +
        "their history is kept and their access is revoked instead."
    );
    if (!ok) return;
    setError(null);
    setNote(null);
    try {
      const result = await api.removeMember(m.id);
      setNote(result.detail);
      list.reload();
    } catch (e) {
      setError(e as ApiError);
    }
  }

  async function setActive(id: number, is_active: boolean) {
    setError(null);
    try {
      await api.patchMember(id, { is_active });
      list.reload();
    } catch (e) {
      setError(e as ApiError);
    }
  }

  async function save(id: number, existingSlackId: string | null) {
    setError(null);
    const slackId = (draft[id]?.slack_user_id ?? existingSlackId ?? "").trim();
    const invalid = invalidSlackId(slackId);
    if (invalid) return setError(invalid);
    try {
      await api.patchMember(id, {
        email: draft[id]?.email?.trim() || null,
        slack_user_id: slackId || null,
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
      {note ? <Banner tone="info">{note}</Banner> : null}

      <div className="filter-bar">
        <input
          className="field"
          placeholder="Full name"
          value={adding.display_name}
          onChange={(e) => setAdding((a) => ({ ...a, display_name: e.target.value }))}
        />
        <input
          className="field"
          type="email"
          placeholder="name@hackerearth.com"
          value={adding.email}
          onChange={(e) => setAdding((a) => ({ ...a, email: e.target.value }))}
          onKeyDown={(e) => e.key === "Enter" && adding.display_name.trim() && add()}
        />
        <input
          className="field"
          placeholder="Slack ID (U0123ABCD)"
          pattern={SLACK_ID_RE.source}
          title="A Slack member id, e.g. U0123ABCD — not a username or display name"
          value={adding.slack_user_id}
          onChange={(e) => setAdding((a) => ({ ...a, slack_user_id: e.target.value }))}
          onKeyDown={(e) => e.key === "Enter" && adding.display_name.trim() && add()}
        />
        <select
          className="field"
          value={adding.role}
          onChange={(e) => setAdding((a) => ({ ...a, role: e.target.value }))}
          aria-label="Role"
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <button
          className="btn btn-primary"
          disabled={busy || !adding.display_name.trim()}
          onClick={add}
        >
          {busy ? "Adding…" : "Add member"}
        </button>
      </div>
      <p className="hint" style={{ marginTop: -4, marginBottom: 12 }}>
        Give them an email and they can sign in with Google straight away — no
        restart, no deploy. A Slack ID lets the plan/update roll call @-mention them —
        copy it from their Slack profile's "Copy member ID", never their name or username.
      </p>

      <Async loading={list.loading} error={list.error} data={list.data}>
        {(rows) => (
          <div className="table-scroll" style={{ border: 0, boxShadow: "none" }}>
            <table>
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Email</th>
                  <th>Slack ID</th>
                  <th>Role</th>
                  <th>Access</th>
                  <th />
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
                              [m.id]: {
                                role: d[m.id]?.role ?? m.role,
                                slack_user_id: d[m.id]?.slack_user_id ?? m.slack_user_id ?? "",
                                email: e.target.value,
                              },
                            }))
                          }
                        />
                      </td>
                      <td>
                        <input
                          className="field"
                          placeholder="U0123ABCD"
                          pattern={SLACK_ID_RE.source}
                          title="A Slack member id, e.g. U0123ABCD — not a username or display name"
                          value={edited?.slack_user_id ?? m.slack_user_id ?? ""}
                          onChange={(e) =>
                            setDraft((d) => ({
                              ...d,
                              [m.id]: {
                                role: d[m.id]?.role ?? m.role,
                                email: d[m.id]?.email ?? m.email ?? "",
                                slack_user_id: e.target.value,
                              },
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
                              [m.id]: {
                                email: d[m.id]?.email ?? m.email ?? "",
                                slack_user_id: d[m.id]?.slack_user_id ?? m.slack_user_id ?? "",
                                role: e.target.value,
                              },
                            }))
                          }
                        >
                          {ROLES.map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <button
                          className={`pill ${m.is_active ? "pill-closed" : "pill-muted"} pill-button`}
                          onClick={() => setActive(m.id, !m.is_active)}
                          title={
                            m.is_active
                              ? "Revoke access — keeps all their history"
                              : "Restore access"
                          }
                        >
                          {m.is_active ? "Active" : "Inactive"}
                        </button>
                      </td>
                      <td>
                        <button
                          className="section-action"
                          disabled={!edited}
                          onClick={() => save(m.id, m.slack_user_id)}
                        >
                          Save
                        </button>
                      </td>
                      <td>
                        <button className="btn btn-danger btn-sm" onClick={() => remove(m)}>
                          Remove
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

      <div className="btn-row" style={{ marginTop: 12 }}>
        {([
          { phase: "morning" as const, label: "Post plan roll call now" },
          { phase: "evening" as const, label: "Post update roll call now" },
        ]).map(({ phase, label }) => (
          <button
            key={phase}
            className="btn btn-secondary"
            disabled={!!busy}
            onClick={() =>
              confirm(
                `Post the ${phase} roll call to Slack now, instead of waiting for its ` +
                  "scheduled time? This is visible to the channel."
              ) && act(phase, () => api.slackRollCall(phase))
            }
          >
            {busy === phase ? "Posting…" : label}
          </button>
        ))}
      </div>
      <p className="hint">
        Runs the same roll call as the 11:05/19:35 schedule, right now, regardless of the time of day.
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
        <LookupList kind="task-types" title="Work types"
                    sub="synced from Jira · offered on the plan and update forms" />
        <LookupList kind="question-types" title="Question types"
                    sub="synced from Jira · optional tag on each ticket" />
      </div>
      <div style={{ marginTop: 12 }}>
        <Integrations />
      </div>
    </>
  );
}
