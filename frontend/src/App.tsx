import { Navigate, Route, Routes } from "react-router-dom";
import "./theme.css";
import "./App.css";
import { Header } from "./components/Header";
import { PeriodPicker } from "./components/PeriodPicker";
import { Banner, Skeleton } from "./components/ui";
import { useAuth } from "./hooks/useAuth";
import { usePeriod } from "./hooks/usePeriod";
import { useTheme } from "./hooks/useTheme";
import { Admin } from "./routes/Admin";
import { Analytics } from "./routes/Analytics";
import { ContentRequests } from "./routes/ContentRequests";
import { Requests } from "./routes/Requests";
import { Login } from "./routes/Login";
import { MemberDetail } from "./routes/MemberDetail";
import { Members } from "./routes/Members";
import { Overview } from "./routes/Overview";
import { PlanForm } from "./routes/PlanForm";
import { UpdateForm } from "./routes/UpdateForm";
import { WorkLog } from "./routes/WorkLog";

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const { user, loading, logout } = useAuth();
  const range = usePeriod();

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
    <div className="wrap">
      <Header user={user} theme={theme} onToggleTheme={toggleTheme} onLogout={logout} />

      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 4 }}>
        <PeriodPicker range={range} />
      </div>

      {!user.member ? (
        <Banner tone="warn">
          Your account isn't linked to a team member yet, so you can read but not
          log work. An admin can link it on the Admin screen.
        </Banner>
      ) : null}

      <Routes>
        <Route path="/" element={<Overview range={range} />} />
        <Route path="/work-log" element={<WorkLog range={range} />} />
        <Route path="/analytics" element={<Analytics range={range} />} />
        <Route path="/members" element={<Members range={range} />} />
        <Route path="/members/:id" element={<MemberDetail range={range} />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/requests" element={<Requests range={range} />} />
        {/* Raw Jira board mirror. Off the nav — /requests supersedes it. */}
        <Route path="/content-requests" element={<ContentRequests />} />
        <Route path="/plans/new" element={<PlanForm me={user.member} />} />
        <Route path="/updates/new" element={<UpdateForm me={user.member} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      <footer className="footer">
        <span className="live-dot" />
        <span>
          {range.from} → {range.to}
        </span>
        <span className="topbar-spacer" />
        <span>Signed in as {user.email}</span>
      </footer>
    </div>
  );
}
