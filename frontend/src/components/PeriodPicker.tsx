import { useId } from "react";
import { DateField } from "./DateField";
import { addDays, dmy, today } from "../format";
import type { Range } from "../hooks/usePeriod";
import type { Period } from "../types";

/** `title` explains what each preset resolves to, since "Week" alone doesn't
 * say whether it means the calendar week or the last seven days. */
const PERIODS: { key: Period; label: string; title: string }[] = [
  { key: "today", label: "Today", title: "Just today" },
  { key: "yesterday", label: "Yesterday", title: "Just yesterday" },
  { key: "week", label: "Last 7 days", title: "The last seven days, ending today" },
  { key: "month", label: "This month", title: "From the 1st of this month to today" },
  { key: "quarter", label: "This quarter", title: "From the start of this quarter to today" },
];

const pretty = dmy;

export function PeriodPicker({ range }: { range: Range }) {
  const id = useId();
  const t = today();
  // A year back is plenty of history to look at; further than that has never
  // once been a real request and just invites picking a meaningless range.
  const earliest = addDays(t, -365);
  const index = PERIODS.findIndex((p) => p.key === range.period);

  /** Arrow keys move and select, Home/End jump to the ends — the standard radio
   * group contract. Roving `tabIndex` takes the unselected options out of the
   * tab order, so without this they'd be unreachable by keyboard entirely. */
  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    let next: number | undefined;
    if (step !== undefined) next = ((index < 0 ? 0 : index) + step + PERIODS.length) % PERIODS.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = PERIODS.length - 1;
    if (next === undefined) return;

    e.preventDefault();
    range.set(PERIODS[next].key);
    const group = e.currentTarget;
    // Focus follows selection, or the keyboard user loses their place.
    requestAnimationFrame(() =>
      group.querySelectorAll<HTMLButtonElement>("[role='radio']")[next]?.focus()
    );
  }

  return (
    <div className="period-picker">
      {/* A radio group, not a row of buttons: exactly one range is active at a
          time, so arrow keys should move between them and a screen reader
          should say "3 of 5" rather than reading five separate toggles. */}
      <div className="period-group" role="radiogroup" aria-label="Date range"
           onKeyDown={onKeyDown}>
        {PERIODS.map((p, i) => {
          const active = range.period === p.key;
          // Custom dates mean nothing is selected, so the first option holds
          // the tab stop — a group with no tabbable child is a keyboard trap.
          const tabbable = active || (index < 0 && i === 0);
          return (
            <button
              key={p.key}
              type="button"
              role="radio"
              aria-checked={active}
              tabIndex={tabbable ? 0 : -1}
              className="period-btn"
              title={p.title}
              onClick={() => range.set(p.key)}
            >
              {p.label}
            </button>
          );
        })}
      </div>

      <div className="period-dates">
        {/* Labels are visible, not just `aria-label`. A bare pair of date boxes
            with an arrow between them relies on sighted guesswork about which
            is which, and the arrow is invisible to a screen reader. */}
        <div className="period-field">
          <label className="label" htmlFor={`${id}-from`}>From</label>
          <DateField
            id={`${id}-from`}
            label="from date"
            value={range.from}
            min={earliest}
            max={range.to < t ? range.to : t}
            onChange={(iso) => iso && range.setCustom(iso, range.to)}
          />
        </div>
        <div className="period-field">
          <label className="label" htmlFor={`${id}-to`}>To</label>
          <DateField
            id={`${id}-to`}
            label="to date"
            value={range.to}
            min={range.from}
            // No future dates: nothing has been logged there, and a range
            // ending in the future is what made every screen read as empty.
            max={t}
            onChange={(iso) => iso && range.setCustom(range.from, iso)}
          />
        </div>
      </div>

      {/* Announced politely so changing the range confirms itself rather than
          leaving a screen-reader user to infer it from the numbers moving. */}
      <p className="period-resolved" aria-live="polite">
        {range.from === range.to
          ? pretty(range.from)
          : `${pretty(range.from)} – ${pretty(range.to)}`}
      </p>
    </div>
  );
}
