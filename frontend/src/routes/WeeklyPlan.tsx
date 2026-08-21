import { useState } from "react";
import { ApiError, api } from "../api";
import { RichText } from "../components/RichText";
import { Banner, SectionHeading, Skeleton } from "../components/ui";
import { isBlankHtml } from "../richtext";
import { useApi } from "../hooks/useApi";
import type { CurrentUser, WeeklyPlanItem, WeeklyPlanStatus } from "../types";

const STATUS_LABEL: Record<WeeklyPlanStatus, string> = {
  yet_to_start: "Yet to start",
  in_progress: "In progress",
  blocked: "Blocked",
  completed: "Completed",
};
// Existing ticket statuses already have pill colours (open/in_progress/blocked/closed) —
// reused here rather than inventing a second colour set for an equivalent meaning.
const PILL_KEY: Record<WeeklyPlanStatus, string> = {
  yet_to_start: "open", in_progress: "in_progress", blocked: "blocked", completed: "closed",
};
// `yet_to_start` is a creation-only default — never a settable target again.
const SETTABLE_STATUSES: WeeklyPlanStatus[] = ["in_progress", "blocked", "completed"];

function istNow(): Date {
  return new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
}
function mondayOf(d: Date): string {
  const back = (d.getDay() + 6) % 7; // Mon=0 .. Sun=6
  const m = new Date(d);
  m.setDate(d.getDate() - back);
  return m.toLocaleDateString("en-CA");
}
/** A `<input type="date">` value ("YYYY-MM-DD") snapped to that week's Monday.
 * Built from the y/m/d components rather than `new Date(v)` — the latter
 * parses as UTC midnight, which `getDay()` then reads back a day off in any
 * timezone behind UTC. */
function mondayOfInputValue(v: string): string {
  const [y, m, d] = v.split("-").map(Number);
  return mondayOf(new Date(y, m - 1, d));
}
const isFriday = () => istNow().getDay() === 5;

type AddWindow = "monday" | "friday" | "closed";

/** New items only: Monday 6:30am-7:30pm files the week, Friday 1:30pm-midnight
 * adds anything unplanned. Status changes (below) aren't gated by this at all —
 * they're open the whole week. */
function addWindowNow(): { window: AddWindow; hint: string } {
  const ist = istNow();
  const day = ist.getDay();
  const mins = ist.getHours() * 60 + ist.getMinutes();
  const MON_OPEN = 6 * 60 + 30, MON_CLOSE = 19 * 60 + 30, FRI_OPEN = 13 * 60 + 30;

  if (day === 1 && mins >= MON_OPEN && mins < MON_CLOSE) {
    return { window: "monday", hint: "New items open until 7:30 PM today." };
  }
  if (day === 5 && mins >= FRI_OPEN) {
    return { window: "friday", hint: "New items open until midnight tonight." };
  }
  if (day === 1 && mins < MON_OPEN) return { window: "closed", hint: "New items open today at 6:30 AM." };
  if (day === 5 && mins < FRI_OPEN) return { window: "closed", hint: "New items open today at 1:30 PM." };
  if (day === 6 || day === 0) return { window: "closed", hint: "New items open Monday at 6:30 AM." };
  return { window: "closed", hint: "New items open Friday at 1:30 PM." };
}

export function WeeklyPlan({ me }: { me: CurrentUser["member"] }) {
  const isLead = me?.role === "admin" || me?.role === "manager";
  const members = useApi(() => (isLead ? api.members() : Promise.resolve([])), [isLead]);
  const [memberId, setMemberId] = useState<number | "all" | null>(null);
  const viewingAll = isLead && memberId === "all";
  const who = viewingAll ? null : (memberId as number | null) ?? me?.id ?? null;
  const viewingSelf = !viewingAll && who === me?.id;

  // Leads aren't pinned to the current week — anyone else still only ever
  // has their own week to look at, so there's nothing for them to pick.
  const [week, setWeek] = useState(() => mondayOf(istNow()));
  const { window: addWindow, hint } = addWindowNow();

  const items = useApi(
    () => {
      if (viewingAll) return api.weeklyPlan(week, undefined);
      return who ? api.weeklyPlan(week, isLead ? who : undefined) : Promise.resolve([]);
    },
    [viewingAll, who, week, isLead]
  );

  if (!me) {
    return (
      <Banner tone="warn">
        Your account isn't linked to a team member, so there's no weekly plan to file.
      </Banner>
    );
  }

  return (
    <>
      <SectionHeading
        title="Weekly plan"
        color="var(--accent-aqua)"
        action={
          isLead ? (
            <div style={{ display: "flex", gap: 8 }}>
              <input
                type="date" className="field" style={{ width: "auto" }}
                value={week} onChange={(e) => setWeek(mondayOfInputValue(e.target.value))}
                aria-label="Week"
              />
              <select
                className="field" style={{ width: "auto" }}
                value={viewingAll ? "all" : who ?? ""}
                onChange={(e) => setMemberId(e.target.value === "all" ? "all" : Number(e.target.value))}
                aria-label="Member"
              >
                <option value="all">All members</option>
                {(members.data ?? []).map((m) => (
                  <option key={m.id} value={m.id}>{m.display_name}</option>
                ))}
              </select>
            </div>
          ) : null
        }
      />
      <p className="tab-blurb">
        Filed Monday morning, reported Friday afternoon.{" "}
        {viewingSelf ? hint : viewingAll ? "Viewing the whole team — read only." : "Viewing another member — read only."}
      </p>

      {/* Not <Async>: it treats an empty array as "nothing to show" and skips
          rendering children entirely — but the Add-item button has to show
          on a fresh Monday with zero items yet, not just once something exists. */}
      {items.loading ? (
        <Skeleton />
      ) : items.error ? (
        <Banner tone="error">{items.error.message}</Banner>
      ) : (
        <WeeklyPlanTable
          items={items.data ?? []}
          editable={viewingSelf}
          addWindow={addWindow}
          monday={week}
          onChange={items.reload}
        />
      )}
    </>
  );
}

function WeeklyPlanTable({
  items, editable, addWindow, monday, onChange,
}: {
  items: WeeklyPlanItem[];
  editable: boolean;
  addWindow: AddWindow;
  monday: string;
  onChange: () => void;
}) {
  const [adding, setAdding] = useState(false);

  return (
    <>
      <div className="table-scroll day-table">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Action / item</th>
              <th>Achievements</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <WeeklyPlanRow key={item.id} item={item} editable={editable} onChange={onChange} />
            ))}
            {items.length === 0 ? (
              <tr>
                <td colSpan={4} className="muted">Nothing planned for this week yet.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {editable && addWindow !== "closed" ? (
        adding ? (
          <AddItemRow
            monday={monday}
            onAdded={onChange}
            onDone={() => setAdding(false)}
          />
        ) : (
          <div className="btn-row">
            <button className="btn btn-secondary" onClick={() => setAdding(true)}>+ Add item</button>
          </div>
        )
      ) : null}
    </>
  );
}

function AddItemRow({
  monday, onAdded, onDone,
}: { monday: string; onAdded: () => void; onDone: () => void }) {
  const [action, setAction] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function add() {
    if (isBlankHtml(action)) return;
    setError(null);
    setSaving(true);
    try {
      await api.createWeeklyPlanItem(monday, action);
      setAction("");
      onAdded();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="card-title">Add item</div>
      {error ? <Banner tone="error">{error.message}</Banner> : null}
      <RichText value={action} onChange={setAction} placeholder="What are you picking up this week?" />
      <div className="btn-row">
        <button className="btn btn-secondary" onClick={onDone}>Done</button>
        <span className="topbar-spacer" />
        <button className="btn btn-primary" disabled={saving || isBlankHtml(action)} onClick={add}>
          {saving ? "Adding…" : "Add item"}
        </button>
      </div>
    </div>
  );
}

function WeeklyPlanRow({
  item, editable, onChange,
}: { item: WeeklyPlanItem; editable: boolean; onChange: () => void }) {
  const [status, setStatus] = useState<WeeklyPlanStatus>(item.status);
  const [achievement, setAchievement] = useState(item.achievement ?? "");
  const [savingStatus, setSavingStatus] = useState(false);
  const [savingAchievement, setSavingAchievement] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const friday = isFriday();
  const statusOptions = Array.from(new Set([item.status, ...SETTABLE_STATUSES]));
  const achievementChanged = achievement !== (item.achievement ?? "");

  async function saveStatus(next: string) {
    const s = next as WeeklyPlanStatus;
    setStatus(s);
    setError(null);
    setSavingStatus(true);
    try {
      await api.patchWeeklyPlanItem(item.id, { status: s });
      onChange();
    } catch (e) {
      setStatus(item.status);
      setError(e as ApiError);
    } finally {
      setSavingStatus(false);
    }
  }

  async function saveAchievement() {
    setError(null);
    setSavingAchievement(true);
    try {
      await api.patchWeeklyPlanItem(item.id, { achievement });
      onChange();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setSavingAchievement(false);
    }
  }

  return (
    <tr>
      <td className="strong">{item.member}</td>
      <td className="text"><RichText value={item.action} readOnly /></td>
      <td className="text">
        {editable && friday ? (
          <>
            <RichText value={achievement} onChange={setAchievement} placeholder="What came of it?" />
            {achievementChanged ? (
              <button
                className="btn btn-secondary" style={{ marginTop: 6 }}
                disabled={savingAchievement} onClick={saveAchievement}
              >
                {savingAchievement ? "Saving…" : "Save"}
              </button>
            ) : null}
          </>
        ) : item.achievement ? (
          <RichText value={item.achievement} readOnly />
        ) : (
          <span className="muted" title="Opens up on Friday">Locked until Friday</span>
        )}
      </td>
      <td>
        {editable ? (
          <>
            <select
              className="field field-inline" value={status} disabled={savingStatus}
              aria-label={`Status for ${item.member}'s item`}
              onChange={(e) => saveStatus(e.target.value)}
            >
              {statusOptions.map((s) => (
                <option key={s} value={s}>{STATUS_LABEL[s]}</option>
              ))}
            </select>
            {error ? (
              <div className="hint" style={{ color: "var(--status-critical)" }}>{error.message}</div>
            ) : null}
          </>
        ) : (
          <span className={`pill pill-${PILL_KEY[item.status]}`}>{STATUS_LABEL[item.status]}</span>
        )}
      </td>
    </tr>
  );
}
