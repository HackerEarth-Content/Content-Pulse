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
