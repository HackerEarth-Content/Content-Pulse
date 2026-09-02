
import type { ReactNode } from "react";
import { useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
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
import { usePeriod, type Range } from "./hooks/usePeriod";
import { useTheme } from "./hooks/useTheme";
import type { CurrentUser } from "./types";
import { Admin } from "./routes/Admin";
import { Analytics } from "./routes/Analytics";
import { ContentHealth } from "./routes/ContentHealth";
import { ContentRequests } from "./routes/ContentRequests";
import { Leaderboard } from "./routes/Leaderboard";
import { Requests } from "./routes/Requests";
import { Login } from "./routes/Login";
import { MemberDetail } from "./routes/MemberDetail";
import { Members } from "./routes/Members";
import { Overview } from "./routes/Overview";
import { PlanBoard } from "./routes/PlanBoard";
import { MyDay } from "./routes/MyDay";
import { QuickLinks } from "./routes/QuickLinks";
import { SkillGraph } from "./routes/SkillGraph";
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

/** The primary nav tabs — kept mounted (instead of torn down by <Routes> on
 * every navigation) so switching between them is instant and doesn't lose
 * in-progress state like unsaved plan rows. Capped at MAX_KEPT_ALIVE: past
 * that, the least-recently-visited tab is unmounted (its state and any
 * fetched data go with it) so a long session doesn't keep every tab ever
 * opened alive in memory forever. */
const MAX_KEPT_ALIVE = 5;

function tabsFor(user: CurrentUser, range: Range): { path: string; element: ReactNode }[] {
  const role = user.member?.role;
  return [
    { path: "/", element: <Overview range={range} /> },
    { path: "/work-log", element: <WorkLog range={range} me={user.member} /> },
    { path: "/analytics", element: <AdminOnly role={role}><Analytics range={range} /></AdminOnly> },
    { path: "/content-health", element: <AdminOnly role={role}><ContentHealth /></AdminOnly> },
    { path: "/members", element: <Members range={range} /> },
    { path: "/admin", element: <Admin /> },
    { path: "/plan-board", element: <PlanBoard /> },
    { path: "/requests", element: <AdminOnly role={role}><Requests range={range} /></AdminOnly> },
    { path: "/leaderboard", element: <Leaderboard range={range} /> },
    { path: "/skills", element: <SkillGraph me={user.member} /> },
    { path: "/my-day", element: <MyDay me={user.member} /> },
    { path: "/weekly-plan", element: <WeeklyPlan me={user.member} /> },
    { path: "/quick-links", element: <QuickLinks me={user.member} /> },
  ];
}

/** Tracks which tab paths to keep mounted, most-recently-visited last.
 * Adjusts during render (React's documented pattern for state derived from a
 * changing prop) rather than in an effect, so there's no extra render where
 * the newly-visited tab is briefly missing from the list. */
function useKeepAliveOrder(current: string, isTab: boolean, max: number): string[] {
  const [order, setOrder] = useState<string[]>(isTab ? [current] : []);
  if (isTab && order[order.length - 1] !== current) {
    const next = [...order.filter((p) => p !== current), current];
    setOrder(next);
    return next.length > max ? next.slice(next.length - max) : next;
  }
  return order;
}

/** Renders every kept-alive tab (hidden unless active) plus a normal
 * <Routes> for everything that isn't a tab: the dynamic member profile,
 * the off-nav Jira mirror, and the old-URL redirects. */
function TabPanes({ user, range }: { user: CurrentUser; range: Range }) {
  const location = useLocation();
  const tabs = tabsFor(user, range);
  const isTab = tabs.some((t) => t.path === location.pathname);
  const order = useKeepAliveOrder(location.pathname, isTab, MAX_KEPT_ALIVE);

  return (
    <>
      {tabs
        .filter((t) => order.includes(t.path))
        .map((t) => (
          <div key={t.path} hidden={t.path !== location.pathname}>
            {t.element}
          </div>
        ))}

      <Routes>
        {/* Declared so the catch-all below doesn't intercept a tab path — the
            actual content for these renders above, outside this <Routes>. */}
        {tabs.map((t) => (
          <Route key={t.path} path={t.path} element={null} />
        ))}
        <Route path="/members/:id" element={<MemberDetail range={range} me={user.member} />} />
        {/* Raw Jira board mirror. Off the nav — /requests supersedes it. */}
        <Route path="/content-requests" element={<ContentRequests />} />
        {/* The old split forms; one screen replaces both. */}
        <Route path="/plans/new" element={<Navigate to="/my-day" replace />} />
        <Route path="/updates/new" element={<Navigate to="/my-day" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
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
      <TabPanes user={user} range={range} />

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
