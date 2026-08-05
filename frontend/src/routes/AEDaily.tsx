import { useState } from "react";
import { ApiError, api } from "../api";
import { Async, Banner, Card, SectionHeading, StatTile } from "../components/ui";
import { num, today } from "../format";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";
import type { CurrentUser } from "../types";

export function AEDaily({ range, me }: { range: Range; me: CurrentUser["member"] }) {
  const p = { from: range.from, to: range.to };
  const metrics = useApi(() => api.aeMetrics(), []);
  const members = useApi(() => api.members({ role: "ae" }), []);
  const grid = useApi(() => api.aeDaily(p), [range.from, range.to]);
  const totals = useApi(() => api.aeAnalytics(p), [range.from, range.to]);

  // Leads log for the whole team; an AE logs for themselves.
  const canLogForOthers = !me || me.role === "admin" || me.role === "manager";
  const [memberId, setMemberId] = useState(me && me.role === "ae" ? String(me.id) : "");
  const [date, setDate] = useState(today());
  const [notes, setNotes] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  // The version we were shown. Sending it back is how the server detects that
  // someone else saved this day in the meantime.
  const existing = (grid.data?.items ?? []).find(
    (r) => r.member_id === Number(memberId) && r.entry_date === date
  );

  async function submit() {
    setError(null);
    setSaved(false);
    setSaving(true);
    try {
      await api.aeUpsert({
        member_id: Number(memberId),
        entry_date: date,
        notes,
        metrics: Object.fromEntries(
          Object.entries(values).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)])
        ),
        version: existing?.updated_at ?? null,
      });
      setSaved(true);
      grid.reload();
      totals.reload();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setSaving(false);
    }
  }

  const dates = [...new Set((grid.data?.items ?? []).map((r) => r.entry_date))].sort();
  const names = [...new Set((grid.data?.items ?? []).map((r) => r.member))].sort();
  const cell = (d: string, m: string) =>
    (grid.data?.items ?? []).find((r) => r.entry_date === d && r.member === m);

  return (
    <>
      <SectionHeading
        title="AE daily"
        color="var(--accent-orange)"
        action={
          <button className="section-action" onClick={() => api.exportAeDaily(p)}>
            Download Excel
          </button>
        }
      />

      <Async loading={totals.loading} error={totals.error} data={totals.data}>
        {(t) => (
          <div className="stat-row">
            {t.totals.map((m) => (
              <StatTile key={m.key} label={m.label} value={num(m.total)} />
            ))}
          </div>
        )}
      </Async>

      <SectionHeading title="Log a day" />
      {error ? (
        <Banner tone={error.code === "stale_update" ? "warn" : "error"}>
          {error.message}
          {error.code === "stale_update" ? (
            <button className="section-action" style={{ marginLeft: 8 }} onClick={grid.reload}>
              Reload
            </button>
          ) : null}
        </Banner>
      ) : null}
      {saved ? <Banner tone="info">Saved.</Banner> : null}

      <Card>
        <div className="field-row">
          <div>
            <label className="label">{canLogForOthers ? "Engineer" : "Logging as"}</label>
            {canLogForOthers ? (
              <select
                className="field"
                value={memberId}
                onChange={(e) => {
                  setMemberId(e.target.value);
                  setSaved(false);
                }}
              >
                <option value="">Select…</option>
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
            <label className="label">Date</label>
            <input
              className="field"
              type="date"
              value={date}
              onChange={(e) => {
                setDate(e.target.value);
                setSaved(false);
              }}
            />
          </div>
        </div>

        {existing ? (
          <p className="hint">
            This day already has an entry — saving replaces it. Values shown below start empty;
            anything you leave blank is left untouched.
          </p>
        ) : null}

        <div className="field-row" style={{ marginTop: 12 }}>
          {(metrics.data ?? []).map((m) => (
            <div key={m.key}>
              <label className="label">{m.label}</label>
              <input
                className="field"
                type="number"
                min={0}
                placeholder={existing ? String(existing.metrics[m.key] ?? 0) : "0"}
                value={values[m.key] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [m.key]: e.target.value }))}
              />
            </div>
          ))}
        </div>

        <div style={{ marginTop: 12 }}>
          <label className="label">Notes — required</label>
          <textarea
            className="field"
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="What did the day look like?"
          />
        </div>

        <div className="btn-row">
          <button
            className="btn btn-primary"
            disabled={saving || !memberId || !notes.trim()}
            onClick={submit}
          >
            {saving ? "Saving…" : existing ? "Replace entry" : "Save entry"}
          </button>
        </div>
      </Card>

      <SectionHeading title="Log" color="var(--accent-orange)" />
      <Async
        loading={grid.loading}
        error={grid.error}
        data={dates.length ? dates : null}
        empty={{ title: "Nothing logged in this range" }}
      >
        {() => (
          <div className="table-scroll">
            <table className="sticky-col">
              <thead>
                <tr>
                  <th>Metric</th>
                  {dates.map((d) =>
                    names.map((n) => (
                      <th key={`${d}-${n}`} className="num">
                        {d} · {n}
                      </th>
                    ))
                  )}
                </tr>
              </thead>
              <tbody>
                {(metrics.data ?? []).map((m) => (
                  <tr key={m.key}>
                    <td className="strong">{m.label}</td>
                    {dates.map((d) =>
                      names.map((n) => (
                        <td key={`${d}-${n}`} className="num">
                          {cell(d, n)?.metrics[m.key] ?? "—"}
                        </td>
                      ))
                    )}
                  </tr>
                ))}
                <tr>
                  <td className="strong">Notes</td>
                  {dates.map((d) =>
                    names.map((n) => (
                      <td key={`${d}-${n}`} className="cell-notes">
                        {cell(d, n)?.notes ?? "—"}
                      </td>
                    ))
                  )}
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </Async>
    </>
  );
}
