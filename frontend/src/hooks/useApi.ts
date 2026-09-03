import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api";
import { useDataVersion } from "./useDataVersion";

export interface State<T> {
  data: T | null;
  loading: boolean;
  error: ApiError | null;
  reload: () => void;
}

/** One fetch, one loading flag, one typed error. `deps` behaves like
 * useEffect's — pass primitives, not object literals.
 *
 * `loading` only turns true for this hook's very first fetch. A `reload()` —
 * called after every save, and every few seconds while a Jira sync is
 * pending — used to flip it back to true every time, which made `<Async>`
 * tear the whole screen down to a skeleton and rebuild it on each one: a
 * one-second "reload" flash for what should have been silent. Once real data
 * has landed once, later fetches happen quietly and just replace it in place.
 */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[]): State<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [tick, setTick] = useState(0);
  const loadedOnce = useRef(false);
  // Bumped when a Jira sync finishes, so every screen picks up the new rows
  // without anyone reloading the page.
  const version = useDataVersion();

  useEffect(() => {
    let cancelled = false;
    if (!loadedOnce.current) setLoading(true);
    setError(null);
    fetcher()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        loadedOnce.current = true;
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof ApiError ? e : new ApiError(0, "network", String(e)));
        setData(null);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, version]);

  return { data, loading, error, reload: useCallback(() => setTick((t) => t + 1), []) };
}
