import { NavLink, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import type { CurrentUser } from "../types";

interface NavItem {
  to: string;
  label: string;
  title: string;
  icon: ReactNode;
  end?: boolean;
  roles?: string[];
}

/** Inline, single-stroke, sized to the text. An icon set would be another
 * dependency and another 40kB for nine glyphs. */
const icon = (d: string) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={d} />
  </svg>
);

/** Ordered by the question each screen answers: what am I doing today, how are
 * we doing, what exactly happened, who did it, what was asked of us, what does
 * it mean. Settings sits apart at the bottom. */
const LINKS: NavItem[] = [
  { to: "/my-day", label: "My day", title: "Plan today and report progress",
    icon: icon("M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z") },
  { to: "/weekly-plan", label: "Weekly plan",
    title: "File Monday morning, report Friday afternoon",
    icon: icon("M3 3v18h18M7 16l3-4 3 2 4-6") },
  { to: "/", label: "Team Overview", end: true, title: "Headline numbers for the period",
    icon: icon("M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z") },
  { to: "/work-log", label: "All tickets", title: "Every ticket, filterable",
    icon: icon("M4 5h16M4 12h16M4 19h10") },
  { to: "/members", label: "Team Members", title: "Per-person workload and effort",
    icon: icon("M16 20v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2M9 3a4 4 0 100 8 4 4 0 000-8zM22 20v-2a4 4 0 00-3-3.9") },
  { to: "/requests", label: "Request streams", roles: ["admin"],
    title: "Requests, assessments, programs and technical writing",
    icon: icon("M4 6h16M4 11h16M4 16h9") },
  { to: "/leaderboard", label: "Leaderboard", title: "Effort logged per person, by area",
    icon: icon("M4 20V14M10 20V10M16 20V6M4 20h16") },
  { to: "/analytics", label: "Insights", roles: ["admin"],
    title: "Delivery, timing, customers and data quality",
    icon: icon("M3 3v18h18M7 15l4-5 3 3 5-7") },
  { to: "/plan-board", label: "Plan board", roles: ["admin", "manager"],
    title: "Who's filed a plan and logged an update today",
    icon: icon("M3 10h18M7 3v4M17 3v4M5 6h14a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2zM7 14h2M11 14h2M15 14h2M7 17h2M11 17h2") },
];

const SETTINGS: NavItem = {
  to: "/admin", label: "Settings", roles: ["admin"],
  title: "People, work types and integrations",
  icon: icon("M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-2.9 1.2V21a2 2 0 11-4 0v-.1A1.7 1.7 0 004.6 19l-.1.1a2 2 0 11-2.8-2.8l.1-.1A1.7 1.7 0 003 13.4H3a2 2 0 110-4h.1A1.7 1.7 0 004.9 6.6L4.8 6.5A2 2 0 117.6 3.7l.1.1a1.7 1.7 0 001.9.3H9.7A1.7 1.7 0 0010.8 2.5V2a2 2 0 114 0v.1a1.7 1.7 0 001.1 1.6 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9v.1a1.7 1.7 0 001.6 1.1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1.1z"),
};

/** Logo swaps with the theme — the dark mark reads on light surfaces and the
 * light mark on dark ones. */
export function BrandLockup({ theme, large = false }: { theme: string; large?: boolean }) {
  const size = large ? 52 : 34;
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
        <span className="brand-sub">HackerEarth - Content</span>
        <span className="brand-mark">Content Pulse</span>
      </span>
    </div>
  );
}

/** The picked date range lives in the URL (period/from/to) so a view is
 * linkable — but that means a bare `to="/members"` drops it on every tab
 * switch, since it's a fresh URL with no query string. Carry just those
 * three keys over; a page's own filters (status, member_id, ...) are that
 * page's business and shouldn't follow you to the next tab. */
function Item({ link, allowed }: { link: NavItem; allowed: boolean }) {
  const location = useLocation();
  if (!allowed) return null;

  const search = new URLSearchParams(location.search);
  const carried = new URLSearchParams();
  for (const key of ["period", "from", "to"]) {
    const value = search.get(key);
    if (value) carried.set(key, value);
  }

  return (
    <NavLink
      to={{ pathname: link.to, search: carried.toString() }}
      end={link.end}
      title={link.title}
      className={({ isActive }) => `side-link${isActive ? " active" : ""}`}
    >
      <span className="side-icon">{link.icon}</span>
      <span>{link.label}</span>
    </NavLink>
  );
}

/** The application frame: a fixed sidebar for navigation, a top bar for
 * context and account.
 *
 * Navigation used to sit in the top bar alongside the brand, theme toggle, name
 * and sign-out — seven destinations on one line, with no room for an eighth. A
 * column gives each one a full row and puts the account controls somewhere they
 * stop competing with them.
 */
export function Shell({
  user,
  theme,
  onToggleTheme,
  onLogout,
  children,
  strip,
  aside,
  trailing,
}: {
  user: CurrentUser;
  theme: string;
  onToggleTheme: () => void;
  onLogout: () => void;
  children: ReactNode;
  strip?: ReactNode;
  aside?: ReactNode;
  /** Sits on the right of the bar, immediately before the account controls —
   *  for status that belongs with "who am I" rather than with the filters. */
  trailing?: ReactNode;
}) {
  const role = user.member?.role;
  return (
    <div className="shell">
      {/* Hiding a link is convenience, not security — every route is gated
          server-side too. */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <BrandLockup theme={theme} />
        </div>

        <nav className="side-nav" aria-label="Sections">
          {LINKS.map((l) => (
            <Item key={l.to} link={l} allowed={!l.roles || (!!role && l.roles.includes(role))} />
          ))}
        </nav>

        <div className="sidebar-foot">
          <Item link={SETTINGS} allowed={!!role && SETTINGS.roles!.includes(role)} />
          <button
            className="side-link"
            onClick={onToggleTheme}
            title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            <span className="side-icon" aria-hidden="true">{theme === "dark" ? "☾" : "☀"}</span>
            <span>{theme === "dark" ? "Dark" : "Light"} theme</span>
          </button>
        </div>
      </aside>

      <div className="shell-main">
        <header className="topbar">
          {aside}
          <span className="topbar-spacer" />
          {trailing}
          <div className="user-chip">
            <strong>{user.member?.display_name ?? user.name ?? user.email}</strong>
            {user.member ? <span className="user-role">{user.member.role}</span> : null}
            <button className="section-action" onClick={onLogout}>Sign out</button>
          </div>
        </header>

        {/* Pinned directly under the bar, so today's state is on every screen
            rather than only the one you happened to open. */}
        {strip}

        <main className="shell-content">{children}</main>
      </div>
    </div>
  );
}
