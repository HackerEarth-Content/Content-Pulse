import { useEffect, useRef } from "react";
import { dmy, relativeTime } from "../format";

/** A Redash sync is a real commitment — up to an hour of live, sequential
 *  queries against production — not a click-and-forget refresh. This asks
 *  first, rather than firing on a bare icon-button click, and says both when
 *  it last ran and roughly when the 15-day job will pick it up on its own,
 *  so "sync now" reads as a deliberate override, not the only way to get
 *  fresh data. Same native `<dialog>` + blurred backdrop as StatusDialog. */
export function RedashSyncDialog({
  lastSynced, onClose, onConfirm,
}: { lastSynced: string | null; onClose: () => void; onConfirm: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  // The API sends naive-UTC timestamps — same parsing rule as relativeTime.
  const lastSyncedUtc = lastSynced
    ? new Date(/[Zz]|[+-]\d\d:\d\d$/.test(lastSynced) ? lastSynced : `${lastSynced}Z`)
    : null;
  const nextEstimate = lastSyncedUtc
    ? new Date(lastSyncedUtc.getTime() + 15 * 24 * 60 * 60 * 1000)
    : null;

  return (
    <dialog ref={ref} className="dialog" onClose={onClose} onCancel={onClose}>
      <div className="dialog-head">
        <div>
          <div className="card-title">Sync from Redash</div>
          <div className="card-sub">This can take a long time — many slow, live queries, not a quick refresh</div>
        </div>
        <button className="section-action" onClick={onClose} aria-label="Close">✕</button>
      </div>

      <div className="stat-row stat-row--bare" style={{ margin: "6px 0 16px" }}>
        <div className="stat">
          <span className="stat-label">Most recent sync</span>
          <div className="stat-value" style={{ fontSize: 16 }}>
            {lastSynced ? relativeTime(lastSynced) : "Never"}
          </div>
        </div>
        <div className="stat">
          <span className="stat-label">Next scheduled sync</span>
          <div className="stat-value" style={{ fontSize: 16 }}>
            {nextEstimate ? dmy(nextEstimate.toLocaleDateString("en-CA")) : "—"}
          </div>
          <div className="stat-sub">~15 days after the last one</div>
        </div>
      </div>

      <p className="hint">
        The scheduled job will pick this up on its own — only sync now if you need this month's
        numbers sooner than that. It'll keep running in the background; you can leave this tab.
      </p>

      <div className="btn-row">
        <span className="topbar-spacer" />
        <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={onConfirm}>Sync now</button>
      </div>
    </dialog>
  );
}
