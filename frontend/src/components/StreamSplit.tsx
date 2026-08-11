import { RankedBars } from "./RankedBars";
import { hours } from "./EffortDrilldown";
import type { AreaByMember } from "../types";

/** Each stream, and who spent the time inside it.
 *
 * The Requests screen could say Content Assessments took 301 hours but not that
 * one person carried a third of it — which is the question actually being asked
 * when a stream looks busy. Streams are ordered by effort rather than ticket
 * count on purpose: twenty feasibility checks and twenty assessments are not
 * the same amount of work, and ranking by count implies they are.
 */
export function StreamSplit({ streams }: { streams: AreaByMember[] }) {
  if (!streams.length) return <p className="muted">No work in this range.</p>;
  const total = streams.reduce((s, a) => s + a.effort_minutes, 0);

  return (
    <div className="stream-split">
      {streams.map((stream) => (
        <section className="card stream-card" key={stream.area}>
          <header className="stream-head">
            <h3>{stream.label}</h3>
            <div className="stream-total">
              <span className="mono">{hours(stream.effort_minutes)}</span>
              <span className="muted">
                {stream.tasks.toLocaleString()} ticket{stream.tasks === 1 ? "" : "s"}
                {total ? ` · ${Math.round((stream.effort_minutes / total) * 100)}% of all effort` : ""}
              </span>
            </div>
          </header>

          {stream.effort_minutes ? (
            <RankedBars
              items={stream.members
                .filter((m) => m.effort_minutes > 0)
                .map((m) => ({
                  key: String(m.member_id),
                  label: m.member,
                  value: m.effort_minutes,
                  sub: `${m.tasks} ticket${m.tasks === 1 ? "" : "s"}, ${m.closed} closed`,
                }))}
              format={hours}
            />
          ) : (
            // Tickets with no effort recorded anywhere in the stream. Saying so
            // beats an empty chart that reads as "no work happened".
            <p className="muted">
              {stream.tasks} ticket{stream.tasks === 1 ? "" : "s"}, none with effort logged.
            </p>
          )}
        </section>
      ))}
    </div>
  );
}
