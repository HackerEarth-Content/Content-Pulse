import { useState } from "react";
import { mins } from "../format";
import { bucketKey, bucketTick, type Bucket } from "../series";

interface Row {
  member: string;
  date: string;
  tasks: number;
  volume: number;
  effort_minutes: number;
}

/** Member × time density. Cell shade is the count relative to the busiest cell,
 * derived with color-mix so it tracks the accent and both themes. */
export function WorkloadHeatmap({ rows, bucket }: { rows: Row[]; bucket: Bucket }) {
  const [metric, setMetric] = useState<"tasks" | "volume" | "effort_minutes">("tasks");
  const cells = new Map<string, number>();
  const members = new Set<string>();
  const columns = new Set<string>();

  for (const row of rows) {
    const col = bucketKey(row.date, bucket);
    members.add(row.member);
    columns.add(col);
    const key = `${row.member}|${col}`;
    cells.set(key, (cells.get(key) ?? 0) + row[metric]);
  }

  const cols = [...columns].sort();
  const names = [...members].sort();
  const busiest = Math.max(1, ...cells.values());

  return (
    <>
      <div className="period-group" style={{ width: "fit-content", marginBottom: 10 }}>
        {(["tasks", "volume", "effort_minutes"] as const).map((m) => (
          <button
            key={m}
            className="period-btn"
            aria-pressed={metric === m}
            onClick={() => setMetric(m)}
          >
            {m === "tasks" ? "Tasks" : m === "volume" ? "Items produced" : "Effort"}
          </button>
        ))}
      </div>
    <div className="table-scroll">
      <table className="sticky-col">
        <thead>
          <tr>
            <th>Member</th>
            {cols.map((c) => (
              <th key={c} className="num">
                {bucketTick(c, bucket)}
              </th>
            ))}
            <th className="num">Total</th>
          </tr>
        </thead>
        <tbody>
          {names.map((name) => {
            const total = cols.reduce((s, c) => s + (cells.get(`${name}|${c}`) ?? 0), 0);
            return (
              <tr key={name}>
                <td className="strong">{name}</td>
                {cols.map((c) => {
                  const n = cells.get(`${name}|${c}`) ?? 0;
                  return (
                    <td
                      key={c}
                      className="num heat"
                      style={
                        n
                          ? {
                              background: `color-mix(in srgb, var(--accent-blue) ${
                                12 + Math.round((n / busiest) * 58)
                              }%, transparent)`,
                            }
                          : undefined
                      }
                      title={`${name} · ${bucketTick(c, bucket)} · ${metric === "effort_minutes" ? mins(n) : n + " " + (metric === "tasks" ? "task" : "item") + (n === 1 ? "" : "s")}`}
                    >
                      {n ? (metric === "effort_minutes" ? mins(n) : n) : ""}
                    </td>
                  );
                })}
                <td className="num strong">{metric === "effort_minutes" ? mins(total || null) : total}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    </>
  );
}
