import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api";

interface State<T> {
  data: T | null;
  loading: boolean;
  error: ApiError | null;
  reload: () => void;
}

/** One fetch, one loading flag, one typed error. `deps` behaves like
 * useEffect's — pass primitives, not object literals. */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[]): State<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcher()
      .then((result) => !cancelled && setData(result))
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
  }, [...deps, tick]);

  return { data, loading, error, reload: useCallback(() => setTick((t) => t + 1), []) };
}
