const STATUS_LABEL: Record<string, string> = {
  open: "Open",
  in_progress: "In Progress",
  blocked: "Blocked",
  closed: "Done",
};

export const statusLabel = (s: string) => STATUS_LABEL[s] ?? s;

export const num = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : n.toLocaleString();

export const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

/** Hours read badly past a day or two — switch units rather than print 412.5h. */
export function hours(h: number | null | undefined): string {
  if (h === null || h === undefined) return "—";
  if (h < 1) return `${Math.round(h * 60)}m`;
  if (h < 48) return `${h.toFixed(1)}h`;
  return `${(h / 24).toFixed(1)}d`;
}

/** Minutes as people say them: 45m, 1h 30m, 2h. Null is "—", never "0m" —
 * unlogged effort is not zero effort. */
export function mins(m: number | null | undefined): string {
  if (m === null || m === undefined) return "—";
  if (m === 0) return "0m";
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return h ? (rest ? `${h}h ${rest}m` : `${h}h`) : `${rest}m`;
}

export function shortDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short" });
}

export const today = () => new Date().toLocaleDateString("en-CA");

/** ISO `2026-08-10` → `10/08/2026`, the format this team writes dates in.
 *
 * Built from the string rather than a Date, because `new Date("2026-08-10")`
 * parses as UTC midnight and renders as the 9th anywhere west of Greenwich.
 * ISO stays the wire and storage format everywhere; this is display only. */
export function dmy(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return y && m && d ? `${d}/${m}/${y}` : iso;
}

/** What a date field should do with what the user typed.
 *
 * Split out of the component so it can be tested: deciding to emit when nothing
 * changed is what made the period picker reset itself on every stray click, and
 * that decision is worth a check rather than a code review.
 *
 * `changed` is false when the parsed date equals what the field already holds —
 * the caller must not fire onChange then, because this runs on blur and so runs
 * on every click away from the field.
 */
export function commitDate(
  raw: string,
  current: string,
  min?: string,
  max?: string
): { iso: string; changed: boolean; invalid: boolean } {
  if (!raw.trim()) {
    return { iso: "", changed: current !== "", invalid: false };
  }
  const iso = fromDmy(raw);
  if (!iso || (min && iso < min) || (max && iso > max)) {
    return { iso: current, changed: false, invalid: true };
  }
  return { iso, changed: iso !== current, invalid: false };
}

/** `10/08/2026` → `2026-08-10`, or null if it isn't a real date.
 *
 * Rejects impossible days rather than letting them roll over: `31/02/2026` is
 * a typo, and Date would silently turn it into 3 March. */
export function fromDmy(text: string): string | null {
  const m = text.trim().match(/^(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{4})$/);
  if (!m) return null;
  const [, d, mo, y] = m.map(Number) as unknown as [string, number, number, number];
  const iso = `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const back = new Date(`${iso}T00:00:00`);
  return back.getFullYear() === y && back.getMonth() + 1 === mo && back.getDate() === d
    ? iso
    : null;
}

export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString("en-CA");
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}
