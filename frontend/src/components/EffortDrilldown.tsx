import { useState } from "react";
import { RankedBars } from "./RankedBars";
import { dmy } from "../format";
import type { EffortBreakdown } from "../types";

const DIMENSIONS = [
  { key: "by_area", label: "Stream" },
  { key: "by_task_type", label: "Work type" },
  { key: "by_customer", label: "Customer" },
  { key: "by_member", label: "Person" },
] as const;

type Dimension = (typeof DIMENSIONS)[number]["key"];

export const hours = (minutes: number): string =>
  minutes >= 60 ? `${Math.round(minutes / 60).toLocaleString()}h` : `${minutes}m`;

/** What a headline effort figure is actually made of.
 *
 * "40h" on its own is a number to disbelieve. Every slice here sums back to the
 * same total the headline uses, and the ticket list underneath means any figure
 * can be traced to the rows behind it rather than taken on trust.
 *
 * The caveats sit next to the number, not on a data-quality page nobody opens:
 * a total that silently omits the 12% of tickets carrying no effort at all is
 * the kind of number that gets quoted in a review.
 */
export function EffortDrilldown({
  data,
  showPeople = true,
}: {
  data: EffortBreakdown;
  showPeople?: boolean;
}) {
  const [dimension, setDimension] = useState<Dimension>("by_area");
  const dimensions = DIMENSIONS.filter((d) => showPeople || d.key !== "by_member");
  const slices = data[dimension];

  return (
    <div className="drilldown">
      <div className="drilldown-head">
        <div>
          <div className="stat-value mono">{hours(data.effort_minutes)}</div>
          <div className="muted">
            logged across {data.tasks.toLocaleString()} tickets
          </div>
        </div>
        <div className="drilldown-caveats">
          {data.tasks_without_effort > 0 ? (
            <span className="pill pill-warn" title="These carry no effort value in Jira, so they add nothing to the total above.">
              {data.tasks_without_effort} with no effort logged
            </span>
          ) : null}
          {data.tasks_with_suspect_effort > 0 ? (
            <span className="pill pill-warn" title="Over 10 hours on a single ticket — kept and counted, but worth checking.">
              {data.tasks_with_suspect_effort} implausible
            </span>
          ) : null}
        </div>
      </div>

      <div className="nav drilldown-tabs" role="tablist" aria-label="Break effort down by">
        {dimensions.map((d) => (
          <button
            key={d.key}
            role="tab"
            aria-selected={dimension === d.key}
            className={`nav-link${dimension === d.key ? " active" : ""}`}
            onClick={() => setDimension(d.key)}
          >
            {d.label}
          </button>
        ))}
      </div>

      {slices.length ? (
        <RankedBars
          items={slices.map((s) => ({
            key: s.key,
            label: s.label || s.key,
            value: s.effort_minutes,
            sub: `${s.tasks} ticket${s.tasks === 1 ? "" : "s"}`,
          }))}
          format={hours}
        />
      ) : (
        <p className="muted">No effort logged in this range.</p>
      )}

      {data.top_tickets.length ? (
        <>
          <h4 className="section-sub">Where the most time went</h4>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Ticket</th>
                  <th>Stream</th>
                  {showPeople ? <th>Who</th> : null}
                  <th>When</th>
                  <th className="num">Effort</th>
                </tr>
              </thead>
              <tbody>
                {data.top_tickets.slice(0, 15).map((t) => (
                  <tr key={t.id}>
                    <td>
                      {t.jira_issue_url ? (
                        <a href={t.jira_issue_url} target="_blank" rel="noreferrer">
                          {t.jira_issue_key}
                        </a>
                      ) : null}{" "}
                      <span className="muted">{t.notes}</span>
                    </td>
                    <td>{t.area_label}</td>
                    {showPeople ? <td>{t.member}</td> : null}
                    <td className="mono">{dmy(t.entry_date)}</td>
                    <td className="num mono">
                      {hours(t.effort_minutes)}
                      {t.suspect ? (
                        <span className="pill pill-warn" title="Implausibly large — counted, not corrected.">?</span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}
