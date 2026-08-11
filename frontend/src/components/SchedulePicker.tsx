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

function options(now: Date) {
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  return [
    { key: "now", label: "Post now", value: "", hint: "Goes out as soon as you save" },
    // The two times the team actually works to: the evening plan drop and the
    // 11am update deadline.
    { key: "evening", label: "8:00 PM today", value: stamp(now, 20), hint: "This evening",
      past: now.getHours() >= 20 },
    { key: "morning", label: "11:00 AM tomorrow", value: stamp(tomorrow, 11),
      hint: "Before the update deadline" },
  ];
}

/** When an entry should reach Jira and Slack.
 *
 * A bare `datetime-local` asks you to assemble a timestamp for what is really a
 * choice between two moments — tonight's drop or tomorrow morning. The presets
 * are those two; the custom field is still there, revealed rather than removed,
 * because a control that only offers presets is a control you fight.
 */
export function SchedulePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  const id = useId();
  const now = new Date();
  const choices = options(now);
  const matched = choices.find((c) => c.value === value);
  const [custom, setCustom] = useState(!matched);

  const pick = (next: string) => {
    setCustom(false);
    onChange(next);
  };

  return (
    <fieldset className="schedule">
      <legend className="label">When should this go out?</legend>

      <div className="schedule-options">
        {choices.map((c) => (
          <label
            key={c.key}
            className={`schedule-option${!custom && matched?.key === c.key ? " selected" : ""}`}
            aria-disabled={c.past || undefined}
          >
            <input
              type="radio"
              name={`${id}-when`}
              checked={!custom && matched?.key === c.key}
              // Choosing a time that has already passed would publish instantly
              // under a label promising 8pm. Disabled rather than silently
              // reinterpreted, and it still announces itself to a screen reader.
              disabled={c.past}
              onChange={() => pick(c.value)}
            />
            <span>
              <span className="schedule-option-label">{c.label}</span>
              <span className="muted">
                {/* Offering "8:00 PM today" at nine at night is a preset that
                    silently means yesterday. Say so instead of hiding it. */}
                {c.past ? "Already gone — pick a time below" : c.hint}
              </span>
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
