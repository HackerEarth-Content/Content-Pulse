import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { Async, Banner, SectionHeading } from "../components/ui";
import { useApi } from "../hooks/useApi";
import type { CurrentUser, QuickLink } from "../types";

const linkIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M10 14a5 5 0 007 0l3-3a5 5 0 00-7-7l-1.5 1.5M14 10a5 5 0 00-7 0l-3 3a5 5 0 007 7l1.5-1.5" />
  </svg>
);
const openIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" />
  </svg>
);

type Panel = { mode: "add" } | { mode: "edit"; link: QuickLink };

/** Every person's own board of saved links — OKR docs, reg. references,
 * dashboards, whatever they keep coming back to. Leads may look at someone
 * else's (read only); nobody edits on another person's behalf. */
export function QuickLinks({ me }: { me: CurrentUser["member"] }) {
  const isLead = me?.role === "admin" || me?.role === "manager";
  const members = useApi(() => (isLead ? api.members() : Promise.resolve([])), [isLead]);
  const [memberId, setMemberId] = useState<number | null>(null);
  const who = memberId ?? me?.id ?? null;
  const viewingSelf = who === me?.id;

  const links = useApi(() => (who ? api.quickLinks(isLead ? who : undefined) : Promise.resolve([])), [who, isLead]);
  const [panel, setPanel] = useState<Panel | null>(null);

  if (!me) {
    return <Banner tone="warn">Your account isn't linked to a team member, so there's nowhere to save links.</Banner>;
  }

  return (
    <>
      <SectionHeading
        title="Quick links"
        color="var(--accent-aqua)"
        action={
          <div style={{ display: "flex", gap: 8 }}>
            {isLead ? (
              <select
                className="field" style={{ width: "auto" }}
                value={who ?? ""}
                onChange={(e) => setMemberId(e.target.value ? Number(e.target.value) : null)}
                aria-label="Member"
              >
                <option value={me.id}>Me ({me.display_name})</option>
                {(members.data ?? [])
                  .filter((m) => m.id !== me.id)
                  .map((m) => (
                    <option key={m.id} value={m.id}>{m.display_name}</option>
                  ))}
              </select>
            ) : null}
            {viewingSelf ? (
              <button className="btn btn-primary" onClick={() => setPanel({ mode: "add" })}>
                + Add link
              </button>
            ) : null}
          </div>
        }
      />
      <p className="tab-blurb">
        {viewingSelf
          ? "OKRs, reg. references, dashboards — anything you keep coming back to."
          : `Viewing ${members.data?.find((m) => m.id === who)?.display_name ?? "their"} links — read only.`}
      </p>

      <Async
        loading={links.loading}
        error={links.error}
        data={links.data}
        empty={{
          title: "No links saved yet",
          hint: viewingSelf ? "Add your first one to get started." : undefined,
        }}
      >
        {(items) => (
          <div className="grid cols-3">
            {items.map((link) => (
              <LinkCard
                key={link.id}
                link={link}
                editable={viewingSelf}
                onEdit={() => setPanel({ mode: "edit", link })}
                onChange={links.reload}
              />
            ))}
          </div>
        )}
      </Async>

      {panel ? (
        <LinkDialog
          panel={panel}
          onClose={() => setPanel(null)}
          onSaved={() => {
            setPanel(null);
            links.reload();
          }}
        />
      ) : null}
    </>
  );
}

function LinkCard({
  link, editable, onEdit, onChange,
}: { link: QuickLink; editable: boolean; onEdit: () => void; onChange: () => void }) {
  const [deleting, setDeleting] = useState(false);

  async function remove() {
    if (!confirm(`Remove "${link.name}"?`)) return;
    setDeleting(true);
    try {
      await api.deleteQuickLink(link.id);
      onChange();
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="card link-card">
      <div className="link-card-head">
        <div className="link-card-title">
          <span className="link-icon">{linkIcon}</span>
          <span className="card-title">{link.name}</span>
        </div>
        {editable ? (
          <div className="link-card-actions">
            <button className="btn-icon" title="Edit" onClick={onEdit}>✎</button>
            <button className="btn-icon" title="Delete" disabled={deleting} onClick={remove}>✕</button>
          </div>
        ) : null}
      </div>
      <a className="link-card-url" href={link.url} target="_blank" rel="noreferrer" title={link.url}>
        <span className="link-card-url-text">{link.url}</span>
        <span className="link-icon-sm">{openIcon}</span>
      </a>
    </div>
  );
}

function LinkDialog({
  panel, onClose, onSaved,
}: { panel: Panel; onClose: () => void; onSaved: () => void }) {
  const editing = panel.mode === "edit" ? panel.link : null;
  const ref = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(editing?.name ?? "");
  const [url, setUrl] = useState(editing?.url ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  // <dialog showModal> centers itself and renders the blurred ::backdrop for
  // free — no positioning or overlay to hand-roll.
  useEffect(() => {
    ref.current?.showModal();
  }, []);

  const valid = name.trim() && url.trim();

  async function save() {
    if (!valid) return;
    setError(null);
    setSaving(true);
    try {
      const body = { name: name.trim(), url: url.trim() };
      if (editing) await api.patchQuickLink(editing.id, body);
      else await api.createQuickLink(body);
      onSaved();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setSaving(false);
    }
  }

  return (
    <dialog ref={ref} className="dialog" onClose={onClose} onCancel={onClose}>
      <div className="dialog-head">
        <span className="card-title">{editing ? "Edit link" : "Add link"}</span>
        <button className="section-action" aria-label="Close" onClick={onClose}>✕</button>
      </div>

      <label className="label">Name</label>
      <input
        className="field" value={name} onChange={(e) => setName(e.target.value)}
        placeholder="Jira dashboard" autoFocus
      />

      <label className="label" style={{ marginTop: 10 }}>Link</label>
      <input
        className="field" type="url" value={url} onChange={(e) => setUrl(e.target.value)}
        placeholder="https://…"
      />

      {error ? <Banner tone="error">{error.message}</Banner> : null}

      <div className="btn-row" style={{ justifyContent: "flex-end" }}>
        <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!valid || saving} onClick={save}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </dialog>
  );
}
