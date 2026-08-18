import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { CATEGORICAL, DONUT, MUTED, TOOLTIP } from "../charts";

export interface Slice {
  key: string;
  label: string;
  value: number;
  colour?: string;
}

/** A 2–3 part split, with the total called out in the hole.
 *
 * Capped at three coloured slices because only three brand hues survive an
 * all-pairs CVD check; anything beyond that folds into a muted "Other" and the
 * legend carries the names. More parts than this wants a ranked bar instead.
 */
export function Donut({
  slices,
  total,
  totalLabel,
  format = (n) => n.toLocaleString(),
  onSelect,
  selected,
  height = 240,
  // Opt-in only — every other Donut on this app stays at the CVD-safe 3.
  // Set this when the slices already carry their own distinguishable
  // `colour`s and folding into "Other" would defeat the point of the chart.
  maxSlices = CATEGORICAL.length,
}: {
  slices: Slice[];
  total?: number;
  totalLabel?: string;
  format?: (n: number) => string;
  onSelect?: (key: string) => void;
  selected?: string | null;
  height?: number;
  maxSlices?: number;
}) {
  const top = slices.slice(0, maxSlices);
  const rest = slices.slice(maxSlices);
  const data = [
    ...top.map((s, i) => ({ ...s, colour: s.colour ?? CATEGORICAL[i] })),
    ...(rest.length
      ? [{
          key: "other",
          label: `Other (${rest.length})`,
          value: rest.reduce((sum, s) => sum + s.value, 0),
          colour: MUTED,
        }]
      : []),
  ].filter((s) => s.value > 0);

  const sum = total ?? data.reduce((s, d) => s + d.value, 0);

  return (
    <div className="donut">
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="label"
            innerRadius={DONUT.innerRadius}
            outerRadius={DONUT.outerRadius}
            paddingAngle={DONUT.paddingAngle}
            isAnimationActive={false}
            onClick={(d: { key?: string }) => d.key && onSelect?.(d.key)}
          >
            {data.map((d) => (
              <Cell
                key={d.key}
                fill={d.colour}
                stroke={DONUT.stroke}
                strokeWidth={DONUT.strokeWidth}
                opacity={selected && selected !== d.key ? 0.35 : 1}
                cursor={onSelect ? "pointer" : undefined}
              />
            ))}
          </Pie>
          <Tooltip
            formatter={(v: number, name: string) => [format(v), name]}
            contentStyle={TOOLTIP}
          />
        </PieChart>
      </ResponsiveContainer>

      {/* The hole carries the total, so the chart answers "how much" as well as
          "what share" without a second tile. */}
      <div className="donut-centre" aria-hidden>
        <span className="donut-total">{format(sum)}</span>
        {totalLabel ? <span className="donut-caption">{totalLabel}</span> : null}
      </div>

      {/* Legend is always present for ≥2 slices — identity must never be
          colour-alone. */}
      <ul className="donut-legend">
        {data.map((d) => (
          <li key={d.key}>
            <button
              className="donut-key"
              onClick={() => onSelect?.(d.key)}
              disabled={!onSelect}
              aria-pressed={selected === d.key}
            >
              <span className="area-dot" style={{ background: d.colour }} />
              <span className="donut-name">{d.label}</span>
              <span className="donut-value mono">{format(d.value)}</span>
              <span className="donut-share mono">
                {sum ? `${Math.round((d.value / sum) * 100)}%` : "—"}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
