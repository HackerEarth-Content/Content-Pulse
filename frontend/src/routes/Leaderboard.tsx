import { api } from "../api";
import { Async, SectionHeading } from "../components/ui";
import { mins } from "../format";
import { useApi } from "../hooks/useApi";
import type { Range } from "../hooks/usePeriod";

/** Fixed, in `AREA_LABELS`'s own order — `tce_subtask` is Jira housekeeping
 * with no effort, so it's left out same as the Requests page leaves it out. */
const COLUMNS: { key: string; label: string }[] = [
  { key: "content_task", label: "Content Tasks" },
  { key: "content_request", label: "Content Requests" },
  { key: "content_assessment", label: "Content Assessments" },
  { key: "hc_request", label: "HC Request" },
  { key: "ht_request", label: "HT Request" },
  { key: "hc_ht_feasibility", label: "HC/HT Feasibility" },
  { key: "technical_writing", label: "Technical Writing" },
];

export function Leaderboard({ range }: { range: Range }) {
  const areas = useApi(() => api.areaByMember({ from: range.from, to: range.to }),
                       [range.from, range.to]);

  return (
    <>
      <SectionHeading title="Leaderboard" color="var(--accent-yellow)" />

      <Async
        loading={areas.loading}
        error={areas.error}
        data={areas.data}
        empty={{ title: "No effort logged in this range" }}
      >
        {(rows) => {
          // Area-major -> member-major: one row per member, one cell per area.
          const byMember = new Map<number, { member: string; byArea: Map<string, number> }>();
          for (const area of rows) {
            for (const m of area.members) {
              const entry = byMember.get(m.member_id) ?? { member: m.member, byArea: new Map() };
              entry.byArea.set(area.area, m.effort_minutes);
              byMember.set(m.member_id, entry);
            }
          }

          const leaders = [...byMember.entries()]
            .map(([id, v]) => ({
              id, member: v.member, byArea: v.byArea,
              total: COLUMNS.reduce((s, c) => s + (v.byArea.get(c.key) ?? 0), 0),
            }))
            .sort((a, b) => b.total - a.total);

          return (
            <div className="table-scroll">
              <table className="sticky-col">
                <thead>
                  <tr>
                    <th>Member</th>
                    {COLUMNS.map((c) => (
                      <th key={c.key} className="num">{c.label}</th>
                    ))}
                    <th className="num">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {leaders.map((r) => (
                    <tr key={r.id}>
                      <td className="strong">{r.member}</td>
                      {COLUMNS.map((c) => {
                        const n = r.byArea.get(c.key);
                        return (
                          <td key={c.key} className="num">
                            {n ? mins(n) : <span className="muted">—</span>}
                          </td>
                        );
                      })}
                      <td className="num strong">{mins(r.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }}
      </Async>
    </>
  );
}
