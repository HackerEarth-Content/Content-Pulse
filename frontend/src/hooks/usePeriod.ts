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
    default:
      // A rolling seven days ending today, never the calendar week.
      //
      // This used to run Monday to Sunday, so opening the app on a Monday asked
      // for six days that hadn't happened yet plus one nobody had filed on, and
      // every screen showed every person on zero. Fixing `resolve_range` on the
      // server was not enough on its own: these bounds are sent as explicit
      // `from`/`to`, and explicit dates always win there.
      return { from: addDays(t, -6), to: t };
  }
}

/** The query string a link to another range-aware page needs to carry, so
 * navigating there doesn't reset the picked period back to the default. */
export function rangeQuery(range: Pick<Range, "period" | "from" | "to">): string {
  return range.period === "custom"
    ? `from=${range.from}&to=${range.to}`
    : `period=${range.period}`;
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
    setCustom: (f, t) => {
      // Setting the range it already has still navigates, which re-renders the
      // tree and drops the named period — so a control that re-announces its
      // value on blur would silently turn "Last 7 days" into a custom range.
      // The guard belongs here as well as in the field: any future caller gets
      // it for free.
      // Compare the *resolved* range, not the raw params: under a named period
      // those are null, so comparing them would never match and the guard would
      // never fire — which is precisely the case it exists for.
      if (bounds.from === f && bounds.to === t) return;
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("from", f);
          next.set("to", t);
          next.delete("period");
          return next;
        },
        { replace: true }
      );
    },
  };
}
