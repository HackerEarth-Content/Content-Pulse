import type { Range } from "../hooks/usePeriod";
import type { Period } from "../types";

const PERIODS: { key: Period; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "week", label: "Week" },
  { key: "month", label: "Month" },
  { key: "quarter", label: "Quarter" },
];

export function PeriodPicker({ range }: { range: Range }) {
  return (
    <div className="period-custom">
      <div className="period-group" role="group" aria-label="Date range">
        {PERIODS.map((p) => (
          <button
            key={p.key}
            className="period-btn"
            aria-pressed={range.period === p.key}
            onClick={() => range.set(p.key)}
          >
            {p.label}
          </button>
        ))}
      </div>
      <input
        className="field"
        type="date"
        value={range.from}
        max={range.to}
        aria-label="From date"
        onChange={(e) => range.setCustom(e.target.value, range.to)}
      />
      <span className="muted">→</span>
      <input
        className="field"
        type="date"
        value={range.to}
        min={range.from}
        aria-label="To date"
        onChange={(e) => range.setCustom(range.from, e.target.value)}
      />
    </div>
  );
}
