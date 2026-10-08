import type { ReactNode } from "react";

const TONES: Record<string, string> = {
  NEW: "neutral", RESEARCHED: "info", QUALIFIED: "good", DISQUALIFIED: "muted", DRAFTED: "info",
  CONTACTED: "info", REPLIED: "good", COMPLETED: "muted", SUPPRESSED: "bad",
  DRAFT: "warn", APPROVED: "info", SCHEDULED: "info", SENT: "info", DELIVERED: "info", FAILED: "bad",
  ACTIVE: "good", PAUSED: "warn",
  PENDING: "warn", GENERATED: "info", CANCELLED: "muted", LIMIT_REACHED: "muted",
  BLOCKED: "bad", INTERESTED: "good", NOT_INTERESTED: "muted", ASKED_QUESTION: "info", REQUESTED_LATER: "warn",
  UNSUBSCRIBE: "bad", OUT_OF_OFFICE: "muted", UNKNOWN: "neutral",
};

// Display names for statuses whose raw value is unclear to a reader.
const LABELS: Record<string, string> = {
  DRAFT: "Waiting for review",
  DRAFTED: "Waiting for review",
  UNSUBSCRIBE: "Opt out",
  ASKED_QUESTION: "Question",
  LIMIT_REACHED: "Sequence complete",
  CANCELLED: "Stopped",
};

export function Badge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="badge muted">—</span>;
  return <span className={`badge ${TONES[value] ?? "neutral"}`}>{LABELS[value] ?? value.replace(/_/g, " ")}</span>;
}

export function Card({ title, actions, children }: { title?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-header">
          {title && <h2>{title}</h2>}
          {actions && <div className="actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function ErrorBanner({ error, onClose }: { error: string | null; onClose?: () => void }) {
  if (!error) return null;
  return (
    <div className="banner error" role="alert">
      <span>{error}</span>
      {onClose && <button className="link" onClick={onClose}>Dismiss</button>}
    </div>
  );
}

export function Notice({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="banner ok">{message}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value}%`;
}

export function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}
