/* Small shared pieces. One file — each is a handful of lines and they always
   travel together. */

import type { ReactNode } from "react";
import { statusLabel } from "../format";
import type { Status } from "../types";

export function SectionHeading({
  title,
  color = "var(--accent-blue)",
  action,
}: {
  title: string;
  color?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-heading">
      <span className="section-dot" style={{ background: color, boxShadow: `0 0 0 3px color-mix(in srgb, ${color} 18%, transparent)` }} />
      <span className="section-title">{title}</span>
      <span className="section-rule" />
      {action}
    </div>
  );
}

export function StatTile({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  accent?: string;
}) {
  return (
    <div className="stat" style={accent ? { borderTop: `2px solid ${accent}` } : undefined}>
      <span className="stat-label">{label}</span>
      <div className="stat-value">{value}</div>
      {sub ? <div className="stat-sub">{sub}</div> : null}
    </div>
  );
}

export const StatusPill = ({ status }: { status: Status }) => (
  <span className={`pill pill-${status}`}>{statusLabel(status)}</span>
);

export const KindPill = ({ kind }: { kind: string }) => (
  <span className={`pill pill-${kind}`}>{kind === "plan" ? "Plan" : "Update"}</span>
);

export function Skeleton({ rows = 3, height = 44 }: { rows?: number; height?: number }) {
  return (
    <div style={{ display: "grid", gap: 8 }} aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ height }} />
      ))}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty">
      <span className="empty-title">{title}</span>
      {hint}
    </div>
  );
}

export function Banner({
  tone = "info",
  children,
}: {
  tone?: "info" | "warn" | "error";
  children: ReactNode;
}) {
  return <div className={`banner banner-${tone}`}>{children}</div>;
}

/** Loading, error and empty are the three states every fetch has. Handling
   them in one place is why no view forgets one. */
export function Async<T>({
  loading,
  error,
  data,
  empty,
  skeleton,
  children,
}: {
  loading: boolean;
  error: { message: string } | null;
  data: T | null;
  empty?: { title: string; hint?: string };
  skeleton?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (loading) return <>{skeleton ?? <Skeleton />}</>;
  if (error) return <Banner tone="error">{error.message}</Banner>;
  if (!data || (Array.isArray(data) && data.length === 0))
    return <EmptyState title={empty?.title ?? "Nothing here yet"} hint={empty?.hint} />;
  return <>{children(data)}</>;
}

export function BarList({
  items,
  max,
}: {
  items: { label: string; value: number; color?: string }[];
  max?: number;
}) {
  const ceiling = max ?? Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="bar-list">
      {items.map((item) => (
        <div className="bar-row" key={item.label}>
          <div>
            <div className="bar-label" title={item.label}>
              {item.label}
            </div>
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{
                  width: `${(item.value / ceiling) * 100}%`,
                  background: item.color ?? "var(--accent-blue)",
                }}
              />
            </div>
          </div>
          <div className="bar-value">{item.value.toLocaleString()}</div>
        </div>
      ))}
    </div>
  );
}

export function Card({
  title,
  sub,
  action,
  children,
}: {
  title?: string;
  sub?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="card">
      {title || sub || action ? (
        <div className="card-head">
          <div>
            {title ? <div className="card-title">{title}</div> : null}
            {sub ? <div className="card-sub">{sub}</div> : null}
          </div>
          {action}
        </div>
      ) : null}
      {children}
    </div>
  );
}
