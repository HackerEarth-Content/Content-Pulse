/** Time-series bucketing.
 *
 * A quarter is ~92 daily points. Rendering one bar per day gives an unreadable
 * axis and a wall of hairlines, so long ranges roll up to weeks or months. The
 * backend always returns zero-filled days, so grouping here is exact — no
 * missing dates to interpolate. */

export type Bucket = "day" | "week" | "month";

const DAY_MS = 86_400_000;

export function bucketFor(from: string, to: string): Bucket {
  const days = Math.round((Date.parse(to) - Date.parse(from)) / DAY_MS) + 1;
  if (days <= 31) return "day";
  if (days <= 120) return "week";
  return "month";
}

/** Monday-anchored, matching the backend's WEEK_START. */
export function bucketKey(iso: string, bucket: Bucket): string {
  if (bucket === "day") return iso;
  const d = new Date(`${iso}T00:00:00`);
  if (bucket === "month") {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
  }
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d.toLocaleDateString("en-CA");
}

/** Sums `keys` across each bucket, keeping the bucket's first date as `date`. */
export function groupSeries<T extends { date: string }>(
  rows: T[],
  bucket: Bucket,
  keys: (keyof T)[]
): T[] {
  if (bucket === "day") return rows;
  const out = new Map<string, T>();
  for (const row of rows) {
    const key = bucketKey(row.date, bucket);
    const acc = out.get(key);
    if (!acc) {
      out.set(key, { ...row, date: key });
      continue;
    }
    for (const k of keys) {
      (acc[k] as number) = ((acc[k] as number) ?? 0) + ((row[k] as number) ?? 0);
    }
  }
  return [...out.values()];
}

export function bucketTick(iso: string, bucket: Bucket): string {
  const d = new Date(`${iso}T00:00:00`);
  if (bucket === "month") return d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short" });
}

export const bucketNoun = (b: Bucket) => (b === "day" ? "day" : b === "week" ? "week" : "month");
