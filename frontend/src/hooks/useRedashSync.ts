import { useEffect, useState } from "react";
import { api } from "../api";
import { bumpDataVersion } from "./useDataVersion";

const CURSOR = "redash";
const POLL_MS = 5000;
const SLOW_POLL_MS = 15000;
// A run is many sequential Redash queries, each potentially slow — that's
// expected, not a fault (see services/content_health.py's docstring). Hide
// the spinner after a while so it doesn't read as stuck, same idea as
// useJiraSync, but scaled up: a Redash sync can legitimately run much longer
// than a Jira one.
const GIVE_UP_MS = 5 * 60_000;
// Keep quietly polling well past that, so a big backfill-scale run still
// updates the screen without anyone reloading — just stop *watching* for
// real eventually.
const HARD_STOP_MS = 30 * 60_000;

export interface RedashSync {
  syncing: boolean;
  lastSynced: string | null;
  lastError: string | null;
  /** Force a fresh sync for this exact period, ignoring the 15-day job. */
  refresh: (from: string, to: string) => void;
}

/** Content Health data refreshes on a 15-day scheduler job (core/scheduler.py)
 * — unlike Jira, nothing here auto-triggers on app open, since a Redash sync
 * can run long and there's no reason to make every sign-in wait on it. This
 * only reports freshness and lets the tab force one on demand. */
export function useRedashSync(): RedashSync {
  const [syncing, setSyncing] = useState(false);
  const [lastSynced, setLastSynced] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [trigger, setTrigger] = useState<{ from: string; to: string; nonce: number } | null>(null);

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
    if (!trigger) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const before = lastSynced;

    setSyncing(true);
    setLastError(null);

    (async () => {
      const started = await api.syncRedash({ from: trigger.from, to: trigger.to }).catch(() => ({ started: false }));
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
        timer = setTimeout(poll, elapsed > GIVE_UP_MS ? SLOW_POLL_MS : POLL_MS);
      };
      timer = setTimeout(poll, POLL_MS);
    })();

    return () => {
      stopped = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger]);

  return {
    syncing,
    lastSynced,
    lastError,
    refresh: (from, to) => {
      if (syncing) return; // a sync is already in flight — don't start a second, racing poll loop.
      setTrigger((t) => ({ from, to, nonce: (t?.nonce ?? 0) + 1 }));
    },
  };
}
