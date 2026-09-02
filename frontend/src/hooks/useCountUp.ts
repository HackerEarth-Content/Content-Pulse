import { useEffect, useRef, useState } from "react";

const DURATION_MS = 600;

/** Animates a stat tile's headline number from its previous value to `value`
 * on change. Off entirely under prefers-reduced-motion, same guard as every
 * other animation in the app (see theme.css). */
export function useCountUp(value: number | null | undefined): number | null {
  const [shown, setShown] = useState(value ?? null);
  const from = useRef(value ?? 0);

  useEffect(() => {
    if (value === null || value === undefined) {
      setShown(null);
      return;
    }
    if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setShown(value);
      from.current = value;
      return;
    }
    const start = from.current;
    const delta = value - start;
    const startedAt = performance.now();
    let frame: number;
    const tick = (now: number) => {
      const t = Math.min(1, (now - startedAt) / DURATION_MS);
      // ease-out cubic — fast start, settles rather than snapping.
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(Math.round(start + delta * eased));
      if (t < 1) frame = requestAnimationFrame(tick);
      else from.current = value;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return shown;
}
