import { shadeFor } from "../charts";

export interface Ranked {
  key: string;
  label: string;
  value: number;
  sub?: string;
}

/** More than three parts, so the written label carries identity and colour is
 * only magnitude — a single-hue ramp, darkest at the top. Six brand hues could
 * not survive an all-pairs CVD check, and a legend of six swatches would have
 * been unreadable for anyone with deuteranopia. */
export function RankedBars({
  items,
  format = (n) => n.toLocaleString(),
  showShare = true,
  onSelect,
  selected,
  max,
}: {
  items: Ranked[];
  format?: (n: number) => string;
  showShare?: boolean;
  onSelect?: (key: string) => void;
  selected?: string | null;
  max?: number;
}) {
  const rows = [...items].sort((a, b) => b.value - a.value);
  const ceiling = max ?? Math.max(1, ...rows.map((r) => r.value));
  const total = rows.reduce((s, r) => s + r.value, 0);

  return (
    <div role="list">
      {rows.map((r, i) => (
        <div
          className="rank-row"
          role="listitem"
          key={r.key}
          onClick={() => onSelect?.(r.key)}
          style={{
            cursor: onSelect ? "pointer" : undefined,
            opacity: selected && selected !== r.key ? 0.5 : 1,
          }}
          title={`${r.label} — ${format(r.value)}${r.sub ? ` · ${r.sub}` : ""}`}
        >
          <div>
            <div className="rank-label">{r.label}</div>
            <div className="rank-track">
              <div
                className="rank-fill"
                style={{
                  width: `${(r.value / ceiling) * 100}%`,
                  background: shadeFor(i, rows.length),
                }}
              />
            </div>
          </div>
          <div className="rank-value">{format(r.value)}</div>
          {showShare ? (
            <div className="rank-share">
              {total ? `${Math.round((r.value / total) * 100)}%` : "—"}
            </div>
          ) : (
            <div className="rank-share">{r.sub ?? ""}</div>
          )}
        </div>
      ))}
    </div>
  );
}
