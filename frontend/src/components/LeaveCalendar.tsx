import { useState } from "react";
import { today } from "../format";

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function monthMatrix(year: number, month: number): (string | null)[][] {
  const first = new Date(year, month, 1);
  const leading = (first.getDay() + 6) % 7; // Monday-first
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const cells: (string | null)[] = Array(leading).fill(null);
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push(`${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`);
  }
  while (cells.length % 7 !== 0) cells.push(null);

  const weeks: (string | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

/** A plain month grid — no picker library, just what `<input type="date">`
 * can't do: showing several selected days at once. Past days are unclickable
 * rather than merely styled dim, since leave can only ever be marked from
 * today onward. */
export function LeaveCalendar({
  selected,
  onToggle,
}: {
  selected: string[];
  onToggle: (iso: string) => void;
}) {
  const min = today();
  const [minYear, minMonth] = min.split("-").map(Number);
  const [cursor, setCursor] = useState({ year: minYear, month: minMonth - 1 });

  const atFloor = cursor.year === minYear && cursor.month === minMonth - 1;
  const label = new Date(cursor.year, cursor.month, 1)
    .toLocaleDateString(undefined, { month: "long", year: "numeric" });

  const step = (delta: number) =>
    setCursor(({ year, month }) => {
      const total = year * 12 + month + delta;
      return { year: Math.floor(total / 12), month: ((total % 12) + 12) % 12 };
    });

  return (
    <div className="leave-cal">
      <div className="leave-cal-head">
        <button
          type="button"
          className="leave-cal-nav leave-cal-nav--prev"
          aria-label="Previous month"
          disabled={atFloor}
          onClick={() => step(-1)}
        >
          ‹
        </button>
        <span className="leave-cal-label">{label}</span>
        <button
          type="button"
          className="leave-cal-nav leave-cal-nav--next"
          aria-label="Next month"
          onClick={() => step(1)}
        >
          ›
        </button>
      </div>

      <div className="leave-cal-grid leave-cal-dow">
        {WEEKDAY_LABELS.map((d) => (
          <span key={d}>{d}</span>
        ))}
      </div>

      {monthMatrix(cursor.year, cursor.month).map((week, i) => (
        <div className="leave-cal-grid" key={i}>
          {week.map((iso, j) => {
            if (!iso) return <span key={j} />;
            // Monday-first grid, so column 5/6 is always Saturday/Sunday —
            // no work happens then, so there's nothing to mark off.
            const isWeekend = j === 5 || j === 6;
            const isPast = iso < min;
            const isSelected = selected.includes(iso);
            return (
              <button
                type="button"
                key={iso}
                className={`leave-cal-day${isSelected ? " is-selected" : ""}${iso === min ? " is-today" : ""}${isWeekend ? " is-weekend" : ""}`}
                disabled={isPast || isWeekend}
                onClick={() => onToggle(iso)}
                aria-pressed={isSelected}
              >
                {Number(iso.slice(8))}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
