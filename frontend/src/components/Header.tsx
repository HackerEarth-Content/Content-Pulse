import { NavLink } from "react-router-dom";
import type { CurrentUser } from "../types";

const LINKS = [
  { to: "/", label: "Overview", end: true },
  { to: "/work-log", label: "Work log" },
  { to: "/analytics", label: "Analytics" },
  { to: "/members", label: "Members" },
  { to: "/ae", label: "AE daily", roles: ["ae", "manager", "admin"] },
  { to: "/content-requests", label: "Requests" },
  { to: "/admin", label: "Admin", roles: ["admin"] },
];

/** Logo swaps with the theme — the dark mark reads on light surfaces and the
 * light mark on dark ones. */
export function BrandLockup({ theme, large = false }: { theme: string; large?: boolean }) {
  const size = large ? 52 : 38;
  return (
    <div className={`brand${large ? " brand-large" : ""}`}>
      <img
        className="brand-logo"
        src={theme === "dark" ? "/hackerearth_logo_light.png" : "/hackerearth_logo.png"}
        alt="HackerEarth"
        width={size}
        height={size}
      />
      <span className="brand-text">
        <span className="brand-mark">ContentOps</span>
        <span className="brand-sub">Daily Tracker</span>
      </span>
    </div>
  );
}

export function Header({
  user,
  theme,
  onToggleTheme,
  onLogout,
}: {
  user: CurrentUser;
  theme: string;
  onToggleTheme: () => void;
  onLogout: () => void;
}) {
  return (
    <header className="topbar">
      <BrandLockup theme={theme} />

      <nav className="nav">
        {/* Hiding a link is convenience, not security — every route is gated
            server-side too. */}
        {LINKS.filter((l) => !l.roles || (user.member && l.roles.includes(user.member.role))).map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.end}
            className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
          >
            {l.label}
          </NavLink>
        ))}
      </nav>

      <span className="topbar-spacer" />

      <NavLink to="/plans/new" className="btn btn-secondary" style={{ textDecoration: "none" }}>
        + Plan
      </NavLink>
      <NavLink to="/updates/new" className="btn btn-primary" style={{ textDecoration: "none" }}>
        + Update
      </NavLink>

      <button
        className="section-action"
        onClick={onToggleTheme}
        aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
      >
        {theme === "dark" ? "☾" : "☀"}
      </button>

      <div className="user-chip">
        <strong>{user.member?.display_name ?? user.name ?? user.email}</strong>
        {user.member ? <span className="user-role">{user.member.role}</span> : null}
        <button className="section-action" onClick={onLogout}>
          Sign out
        </button>
      </div>
    </header>
  );
}
