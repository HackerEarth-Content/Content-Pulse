import { useEffect, useState } from "react";
import { api } from "../api";
import { bumpDataVersion } from "./useDataVersion";

const CURSOR = "jira_backfill";
const POLL_MS = 2000;
const GIVE_UP_MS = 60_000;

/** Refresh Jira data when the dashboard opens, then refresh the screen when it
 * lands.
 *
 * Firing the sync alone is not enough: the dashboard renders from the database
 * immediately, so a sync that finishes two seconds later would only show up on
 * the *next* visit — which is the opposite of what opening the app is supposed
 * to do. So this watches the sync cursor and bumps the data version once it
 * moves, and every `useApi` on screen refetches in place.
 *
 * Deliberately never blocks the first paint. Stale-but-instant beats a spinner
 * over the whole dashboard while Jira is consulted.
 */
export interface JiraSync {
  syncing: boolean;
  /** When the last sync finished, ISO, or null if it has never run. */
  lastSynced: string | null;
  /** Force a sync now, ignoring the cooldown. Wired to the toolbar button. */
  refresh: () => void;
}

export function useJiraSync(enabled: boolean): JiraSync {
  const [syncing, setSyncing] = useState(false);
  const [lastSynced, setLastSynced] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;

    const cursorTime = async (): Promise<string | null> => {
      const rows = await api.syncStatus().catch(() => []);
      return rows.find((r) => r.key === CURSOR)?.last_synced_at ?? null;
    };

    (async () => {
      const before = await cursorTime();
      if (stopped) return;
      setLastSynced(before);

      // On the automatic pass the server may decline — a sync is already
      // running, or one ran inside the cooldown — and that's fine, the data is
      // already fresh. Pressing the button forces it, because someone pressing
      // refresh has a reason to think otherwise.
      const started = await api.syncJira(nonce > 0).catch(() => ({ started: false }));
      if (stopped || !started.started) return;

      setSyncing(true);
      const deadline = Date.now() + GIVE_UP_MS;
      const poll = async () => {
        if (stopped) return;
        const now = await cursorTime();
        if (now && now !== before) {
          setSyncing(false);
          setLastSynced(now);
          bumpDataVersion();
          return;
        }
        if (Date.now() > deadline) {
          // The sync may still be running; it simply stops being worth
          // watching. Whatever it writes shows up on the next navigation.
          setSyncing(false);
          return;
        }
        timer = setTimeout(poll, POLL_MS);
      };
      timer = setTimeout(poll, POLL_MS);
    })();

    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [enabled, nonce]);

  return { syncing, lastSynced, refresh: () => setNonce((n) => n + 1) };
}
