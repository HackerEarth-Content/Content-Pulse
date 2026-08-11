import { relativeTime } from "../format";
import type { JiraSync } from "../hooks/useJiraSync";

/** Freshness, and a way to force it.
 *
 * The time matters more than the button. A sync already runs when the dashboard
 * opens and every 30 minutes after, so most of the time there is nothing to
 * press — what people actually need to know is whether what they're looking at
 * is current. Saying so removes the reason to press it at all.
 */
export function SyncButton({ sync }: { sync: JiraSync }) {
  const { syncing, lastSynced, refresh } = sync;

  return (
    <span className="sync">
      <span className="sync-age" aria-live="polite">
        {syncing
          ? "Syncing from Jira…"
          : lastSynced
            ? `Jira synced ${relativeTime(lastSynced)}`
            : "Not synced yet"}
      </span>
      <button
        className="sync-btn"
        onClick={refresh}
        disabled={syncing}
        title={syncing ? "Sync in progress" : "Pull the latest tickets and effort from Jira"}
        aria-label="Sync from Jira now"
      >
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
             strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"
             className={syncing ? "spin" : undefined} aria-hidden="true">
          <path d="M21 12a9 9 0 11-2.6-6.4M21 3v6h-6" />
        </svg>
      </button>
    </span>
  );
}
