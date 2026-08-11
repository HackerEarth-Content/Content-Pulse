import { useEffect, useId, useRef, useState } from "react";
import { commitDate, dmy } from "../format";

/** A date input that reads and writes dd/mm/yyyy.
 *
 * `<input type="date">` renders in whatever locale the *browser* is set to —
 * not the page's `lang`, not the OS — so on a US-configured Chrome our dates
 * showed as mm/dd/yyyy with no way to change it from here. 08/10/2026 meaning
 * either August or October, silently, is worse than no format at all.
 *
 * So the visible control is a text field we format ourselves, and the native
 * picker is kept behind a calendar button via `showPicker()` — you still get
 * the OS calendar, month navigation and mobile date wheel, without inheriting
 * its formatting. The value crossing `onChange` is always ISO.
 */
export function DateField({
  value,
  onChange,
  label,
  min,
  max,
  className = "field",
  id: providedId,
  ariaLabel,
}: {
  value: string;
  onChange: (iso: string) => void;
  label?: string;
  min?: string;
  max?: string;
  className?: string;
  id?: string;
  ariaLabel?: string;
}) {
  const generated = useId();
  const id = providedId ?? generated;
  const native = useRef<HTMLInputElement>(null);
  const [text, setText] = useState(() => dmy(value));
  const [bad, setBad] = useState(false);

  // Follow the value when something else changes it — a period preset, a form
  // reset — but not while the field is being typed into.
  useEffect(() => {
    if (document.activeElement?.id !== id) {
      setText(value ? dmy(value) : "");
      setBad(false);
    }
  }, [value, id]);

  /** Only ever fires `onChange` when the date genuinely differs.
   *
   * This runs on blur, so it runs when you click the calendar button, tab away,
   * or click anywhere else on the page. Firing unconditionally meant every one
   * of those re-announced the same date to the parent — which, for the period
   * picker, rewrote the URL and flipped the selected preset from "Last 7 days"
   * to a custom range on a click that changed nothing. */
  const commit = (raw: string) => {
    const { iso, changed, invalid } = commitDate(raw, value, min, max);
    setBad(invalid);
    // Keep what they typed when it's invalid: snapping back to the old value
    // mid-edit loses the input and gives no clue what was wrong with it.
    if (invalid) return;
    // Re-render the canonical spelling ("1/8/2026" → "01/08/2026") even when
    // the underlying date is unchanged.
    setText(iso ? dmy(iso) : "");
    if (changed) onChange(iso);
  };

  return (
    <span className="datefield">
      <input
        id={id}
        className={`${className}${bad ? " is-invalid" : ""}`}
        value={text}
        inputMode="numeric"
        placeholder="dd/mm/yyyy"
        aria-label={ariaLabel ?? label}
        aria-invalid={bad || undefined}
        onChange={(e) => setText(e.target.value)}
        onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit(e.currentTarget.value);
        }}
      />

      {/* Hidden from layout but still a real input, so `showPicker()` has
          something to open and the browser keeps its calendar behaviour. */}
      <input
        ref={native}
        type="date"
        className="datefield-native"
        tabIndex={-1}
        aria-hidden="true"
        value={value || ""}
        min={min}
        max={max}
        onChange={(e) => {
          setText(e.target.value ? dmy(e.target.value) : "");
          setBad(false);
          // Same guard as `commit`: the picker fires on open in some browsers,
          // re-emitting the date already selected.
          if (e.target.value !== value) onChange(e.target.value);
        }}
      />

      <button
        type="button"
        className="datefield-btn"
        aria-label={`Open calendar${label ? ` for ${label}` : ""}`}
        onClick={() => {
          const el = native.current;
          if (!el) return;
          // showPicker throws if the browser blocks it outside a user gesture;
          // focusing is a usable fallback rather than a crash.
          try {
            el.showPicker();
          } catch {
            el.focus();
          }
        }}
      >
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
             strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
          <path d="M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z" />
        </svg>
      </button>
    </span>
  );
}
