import { useEffect, useState } from "react";
import { api } from "../api";
import { bumpDataVersion } from "./useDataVersion";

const CURSOR = "content_issues";
const POLL_MS = 3000;
const GIVE_UP_MS = 2 * 60_000;
const HARD_STOP_MS = 10 * 60_000;

export interface ContentIssueSync {
  syncing: boolean;
  lastSynced: string | null;
  lastError: string | null;
  refresh: () => void;
}

/** Content issue data refreshes on the Friday scheduler job
 * (core/scheduler.py) — this only reports freshness and lets the tab force a
 * sync on demand, same shape as useRedashSync but with no date params since
 * the sync always re-mirrors the whole board. */
export function useContentIssueSync(): ContentIssueSync {
  const [syncing, setSyncing] = useState(false);
  const [lastSynced, setLastSynced] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let stopped = false;
    api.syncStatus().then((rows) => {
      if (stopped) return;
      const row = rows.find((r) => r.key === CURSOR);
      setLastSynced(row?.last_synced_at ?? null);
      setLastError(row?.status === "error" ? row.error : null);
    }).catch(() => {});
    return () => {
      stopped = true;
    };
  }, []);

  useEffect(() => {
    if (nonce === 0) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const before = lastSynced;

    setSyncing(true);
    setLastError(null);

    (async () => {
      const started = await api.syncContentIssues().catch(() => ({ started: false }));
      if (stopped || !started.started) {
        if (!stopped) setSyncing(false);
        return;
      }
      const startedAt = Date.now();
      const poll = async () => {
        if (stopped) return;
        const rows = await api.syncStatus().catch(() => []);
        const row = rows.find((r) => r.key === CURSOR);
        if (row?.last_synced_at && row.last_synced_at !== before) {
          setSyncing(false);
          setLastSynced(row.last_synced_at);
          setLastError(row.status === "error" ? row.error : null);
          bumpDataVersion();
          return;
        }
        const elapsed = Date.now() - startedAt;
        if (elapsed > HARD_STOP_MS) {
          setSyncing(false);
          return;
        }
        if (elapsed > GIVE_UP_MS) setSyncing(false);
        timer = setTimeout(poll, POLL_MS);
      };
      timer = setTimeout(poll, POLL_MS);
    })();

    return () => {
      stopped = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce]);

  return {
    syncing,
    lastSynced,
    lastError,
    refresh: () => {
      if (syncing) return;
      setNonce((n) => n + 1);
    },
  };
}
