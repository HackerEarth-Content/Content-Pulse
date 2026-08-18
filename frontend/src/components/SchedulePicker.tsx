import { useId, useState } from "react";

/** Local `YYYY-MM-DDTHH:MM`, the format `datetime-local` speaks.
 * Built from local parts rather than `toISOString()`, which converts to UTC and
 * would schedule an 8pm IST post for 2:30am. */
function stamp(day: Date, hour: number, minute = 0): string {
  const d = new Date(day);
  d.setHours(hour, minute, 0, 0);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

const OPTIONS = [
  { key: "now", label: "Post now", value: "", hint: "Goes out as soon as you save" },
];

/** When an entry should reach Jira and Slack — post now, or hold it for a
 * specific time you pick. */
export function SchedulePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  const id = useId();
  const now = new Date();
  const matched = OPTIONS.find((c) => c.value === value);
  const [custom, setCustom] = useState(!matched);

  const pick = (next: string) => {
    setCustom(false);
    onChange(next);
  };

  return (
    <fieldset className="schedule">
      <legend className="label">When should this go out?</legend>

      <div className="schedule-options">
        {OPTIONS.map((c) => (
          <label
            key={c.key}
            className={`schedule-option${!custom && matched?.key === c.key ? " selected" : ""}`}
          >
            <input
              type="radio"
              name={`${id}-when`}
              checked={!custom && matched?.key === c.key}
              onChange={() => pick(c.value)}
            />
            <span>
              <span className="schedule-option-label">{c.label}</span>
              <span className="muted">{c.hint}</span>
            </span>
          </label>
        ))}

        <label className={`schedule-option${custom ? " selected" : ""}`}>
          <input
            type="radio"
            name={`${id}-when`}
            checked={custom}
            onChange={() => setCustom(true)}
          />
          <span>
            <span className="schedule-option-label">At a specific time</span>
            <span className="muted">Choose the date and time</span>
          </span>
        </label>
      </div>

      {custom ? (
        <div className="schedule-custom">
          <label className="label" htmlFor={`${id}-at`}>Date and time</label>
          <input
            id={`${id}-at`}
            className="field"
            type="datetime-local"
            value={value}
            min={stamp(now, now.getHours(), now.getMinutes())}
            onChange={(e) => onChange(e.target.value)}
          />
        </div>
      ) : null}

      <p className="schedule-summary" aria-live="polite">
        {value
          ? `Held until ${new Date(value).toLocaleString(undefined, {
              weekday: "short", day: "numeric", month: "short",
              hour: "numeric", minute: "2-digit",
            })}.`
          : "Nothing is held back — this posts straight away."}
      </p>
    </fieldset>
  );
}
