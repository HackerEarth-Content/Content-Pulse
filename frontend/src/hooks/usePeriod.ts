import { useSearchParams } from "react-router-dom";
import { addDays, today } from "../format";
import type { Period } from "../types";

export interface Range {
  from: string;
  to: string;
  period: Period | "custom";
  set: (p: Period) => void;
  setCustom: (from: string, to: string) => void;
}

function boundsFor(period: Period): { from: string; to: string } {
  const t = today();
  switch (period) {
    case "today":
      return { from: t, to: t };
    case "yesterday":
      return { from: addDays(t, -1), to: addDays(t, -1) };
    case "month": {
      const d = new Date(`${t}T00:00:00`);
      const first = new Date(d.getFullYear(), d.getMonth(), 1);
      return { from: first.toLocaleDateString("en-CA"), to: t };
    }
    case "quarter": {
      const d = new Date(`${t}T00:00:00`);
      const first = new Date(d.getFullYear(), Math.floor(d.getMonth() / 3) * 3, 1);
      return { from: first.toLocaleDateString("en-CA"), to: t };
    }
    default: {
      // Week starts Monday, matching the backend's WEEK_START.
      const d = new Date(`${t}T00:00:00`);
      const monday = addDays(t, -((d.getDay() + 6) % 7));
      return { from: monday, to: addDays(monday, 6) };
    }
  }
}

/** The range lives in the URL, so any view is linkable and survives reload. */
export function usePeriod(fallback: Period = "week"): Range {
  const [params, setParams] = useSearchParams();
  const from = params.get("from");
  const to = params.get("to");
  const period = (params.get("period") as Period) ?? fallback;
  const bounds = from && to ? { from, to } : boundsFor(period);

  return {
    ...bounds,
    period: from && to ? "custom" : period,
    set: (p) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("period", p);
          next.delete("from");
          next.delete("to");
          return next;
        },
        { replace: true }
      ),
    setCustom: (f, t) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("from", f);
          next.set("to", t);
          next.delete("period");
          return next;
        },
        { replace: true }
      ),
  };
}
