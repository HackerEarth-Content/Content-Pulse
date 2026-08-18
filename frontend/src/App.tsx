
import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import "./theme.css";
import "./App.css";

import { PeriodPicker } from "./components/PeriodPicker";
import { Shell } from "./components/Shell";
import { SyncButton } from "./components/SyncButton";
import { TodayStrip } from "./components/TodayStrip";
import { Banner, Skeleton } from "./components/ui";
import { dmy } from "./format";
import { useAuth } from "./hooks/useAuth";
import { useJiraSync } from "./hooks/useJiraSync";
import { usePeriod } from "./hooks/usePeriod";
import { useTheme } from "./hooks/useTheme";
import { Admin } from "./routes/Admin";
import { Analytics } from "./routes/Analytics";
import { ContentRequests } from "./routes/ContentRequests";
import { Leaderboard } from "./routes/Leaderboard";
import { Requests } from "./routes/Requests";
import { Login } from "./routes/Login";
import { MemberDetail } from "./routes/MemberDetail";
import { Members } from "./routes/Members";
import { Overview } from "./routes/Overview";
import { PlanBoard } from "./routes/PlanBoard";
import { MyDay } from "./routes/MyDay";
import { WeeklyPlan } from "./routes/WeeklyPlan";
import { WorkLog } from "./routes/WorkLog";

const REVIEW_FORM_URL =
  "https://docs.google.com/forms/d/e/1FAIpQLSdKp8mrHZHsExTXTXPXajJ9h0NVfo53lfD4fj8XYOQTYJQNAQ/viewform?usp=publish-editor";

/** Nav already hides the link for anyone but an admin; this is the same
 * check applied to the route itself, so pasting the URL doesn't get you
 * further than a "no access" banner — the backend refuses the data either
 * way. */
function AdminOnly({ role, children }: { role?: string; children: ReactNode }) {
  if (role !== "admin") {
    return <Banner tone="warn">No access — this section is limited to admins.</Banner>;
  }
  return <>{children}</>;
}

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const { user, loading, logout } = useAuth();
  const range = usePeriod();

  // Opening the dashboard refreshes ticket and effort data from Jira, then
  // refreshes the screen when it lands. Never blocks the first paint.
  const sync = useJiraSync(!!user);

  if (loading) {
    return (
      <div className="wrap">
        <Skeleton rows={4} height={64} />
      </div>
    );
  }

  // Everything is behind sign-in — this dashboard reports on named people's
  // work, so there is no signed-out view.
  if (!user) return <Login />;

  return (
    <Shell
      user={user}
      theme={theme}
      onToggleTheme={toggleTheme}
      onLogout={logout}
      aside={<PeriodPicker range={range} />}
      trailing={<SyncButton sync={sync} />}
      strip={<TodayStrip me={user.member} />}
    >
      <Routes>
        <Route path="/" element={<Overview range={range} />} />
        <Route path="/work-log" element={<WorkLog range={range} me={user.member} />} />
        <Route path="/analytics" element={
          <AdminOnly role={user.member?.role}><Analytics range={range} /></AdminOnly>
        } />
        <Route path="/members" element={<Members range={range} />} />
        <Route path="/members/:id" element={<MemberDetail range={range} />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/plan-board" element={<PlanBoard />} />
        <Route path="/requests" element={
          <AdminOnly role={user.member?.role}><Requests range={range} /></AdminOnly>
        } />
        <Route path="/leaderboard" element={<Leaderboard range={range} />} />
        {/* Raw Jira board mirror. Off the nav — /requests supersedes it. */}
        <Route path="/content-requests" element={<ContentRequests />} />
        <Route path="/my-day" element={<MyDay me={user.member} />} />
        <Route path="/weekly-plan" element={<WeeklyPlan me={user.member} />} />
        {/* The old split forms; one screen replaces both. */}
        <Route path="/plans/new" element={<Navigate to="/my-day" replace />} />
        <Route path="/updates/new" element={<Navigate to="/my-day" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      <footer className="footer">
        <span className="live-dot" />
        <span>
          {dmy(range.from)} → {dmy(range.to)}
        </span>
        <span className="topbar-spacer" />
        <a className="tag" href={REVIEW_FORM_URL} target="_blank" rel="noreferrer">Leave a review</a>
        <span>Signed in as {user.email}</span>
      </footer>
    </Shell>
  );
}
