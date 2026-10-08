import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBanner, Notice, when } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { ClaimRow, ServiceRow } from "../types";

export default function Care() {
  const claims = useAsync(() => api.get<ClaimRow[]>("/warranty-claims"));
  const services = useAsync(() => api.get<ServiceRow[]>("/service-requests"));
  const action = useAction();
  return (
    <>
      <div className="page-header">
        <h1>Warranty &amp; Service</h1>
        <button onClick={async () => {
          const r = await action.run("lifecycle", () => api.post<{ sent: number; blocked: number; deferred: number; skipped_existing: number }>("/lifecycle/run"));
          if (r) action.setNotice(`Lifecycle follow-ups: ${r.sent} sent, ${r.deferred} deferred by the frequency limit, ${r.blocked} blocked by preferences/rules, ${r.skipped_existing} already sent.`);
        }}>Run lifecycle follow-ups now</button>
      </div>
      <p className="muted page-sub">The AI runs a basic eligibility check and pulls the relevant policy text. Decisions stay with you unless you enable auto-approval in Automation rules.</p>
      <ErrorBanner error={claims.error ?? services.error ?? action.error} onClose={() => action.setError(null)} />
      <Notice message={action.notice} />
      <h2 className="section-title">Warranty claims</h2>
      {claims.data?.length === 0 && <Card><Empty>No warranty claims.</Empty></Card>}
      <div className="approval-grid">
        {claims.data?.map((c) => <ClaimCard key={c.id} c={c} onDone={claims.reload} run={action.run} />)}
      </div>
      <h2 className="section-title">Service &amp; repair requests</h2>
      {services.data?.length === 0 && <Card><Empty>No service requests.</Empty></Card>}
      <div className="approval-grid">
        {services.data?.map((s) => <ServiceCard key={s.id} s={s} onDone={services.reload} run={action.run} />)}
      </div>
    </>
  );
}

type Run = ReturnType<typeof useAction>["run"];

function ClaimCard({ c, onDone, run }: { c: ClaimRow; onDone: () => void; run: Run }) {
  const [note, setNote] = useState(c.resolution_note ?? "");
  const e = c.eligibility;
  const decide = async (status: string) => {
    if (await run(status, () => api.patch(`/warranty-claims/${c.id}`, { status, note }), `Claim ${status.toLowerCase().replace(/_/g, " ")}.`)) onDone();
  };
  const open = !["COMPLETED", "REJECTED"].includes(c.status);
  return (
    <article className="approval-card">
      <header className="approval-head">
        <div>
          <div className="approval-meta"><Badge value={c.status} />{e.likely_eligible === true && <span className="badge good">rules: likely eligible</span>}{e.likely_eligible === false && <span className="badge bad">rules: likely not eligible</span>}</div>
          <h3 className="approval-title">{c.product_name} — <Link to={`/customers/${c.customer_id}`}>{c.customer_name}</Link></h3>
        </div>
        <span className="muted small">{when(c.created_at)}</span>
      </header>
      <blockquote>{c.issue}</blockquote>
      <h3>Eligibility check (deterministic)</h3>
      <ul className="checklist">
        {e.checks?.map((ch) => <li key={ch.check} className={ch.passed ? "pass" : "fail"}><span>{ch.passed ? "✓" : "✕"}</span> {ch.check}{ch.detail && <span className="reason"> — {ch.detail}</span>}</li>)}
      </ul>
      {!!e.policy_excerpts?.length && (
        <details><summary className="small">Relevant policy text ({e.policy_excerpts.length})</summary>
          {e.policy_excerpts.map((x, i) => <p key={i} className="small excerpt"><b>{x.title}{x.section && ` › ${x.section}`}:</b> {x.text}</p>)}
        </details>
      )}
      {open ? (
        <div className="stack">
          <input placeholder="Note to the customer (required to reject)" value={note} onChange={(ev) => setNote(ev.target.value)} />
          <div className="actions">
            <button className="primary" onClick={() => decide("APPROVED")}>Approve</button>
            <button onClick={() => decide("MORE_INFORMATION_REQUIRED")}>Ask for more info</button>
            <button className="danger-outline" onClick={() => decide("REJECTED")}>Reject</button>
            {c.status === "APPROVED" && <button onClick={() => decide("COMPLETED")}>Mark completed</button>}
          </div>
        </div>
      ) : <p className="small muted">Decision: {c.resolution_note}</p>}
    </article>
  );
}

const NEXT: Record<string, string[]> = {
  PENDING_CONFIRMATION: ["CONFIRMED", "CANCELLED"],
  CONFIRMED: ["IN_PROGRESS", "RESCHEDULED", "COMPLETED", "CANCELLED"],
  RESCHEDULED: ["CONFIRMED", "IN_PROGRESS", "CANCELLED"],
  IN_PROGRESS: ["COMPLETED", "CANCELLED"],
};

function ServiceCard({ s, onDone, run }: { s: ServiceRow; onDone: () => void; run: Run }) {
  const defaultTime = s.preferred_date ? `${s.preferred_date}T09:00` : "";
  const [when_, setWhen] = useState(s.scheduled_for ? s.scheduled_for.slice(0, 16) : defaultTime);
  const [note, setNote] = useState(s.owner_note ?? "");
  const update = async (status: string) => {
    const scheduled_for = when_ ? new Date(when_).toISOString() : null;
    if (await run(status, () => api.patch(`/service-requests/${s.id}`, { status, scheduled_for, note }), `Request ${status.toLowerCase().replace(/_/g, " ")}.`)) onDone();
  };
  return (
    <article className="approval-card">
      <header className="approval-head">
        <div>
          <div className="approval-meta"><Badge value={s.status} /></div>
          <h3 className="approval-title">{s.product_name} — <Link to={`/customers/${s.customer_id}`}>{s.customer_name}</Link></h3>
        </div>
        <span className="muted small">{when(s.created_at)}</span>
      </header>
      <blockquote>{s.issue}</blockquote>
      <p className="small">Prefers: <b>{s.preferred_date ?? "any date"} {s.preferred_time}</b> · {s.contact_phone || s.contact_email}</p>
      {s.scheduled_for && <p className="small">Appointment: <b>{when(s.scheduled_for)}</b></p>}
      {NEXT[s.status] && (
        <div className="stack">
          <div className="inline-form">
            <input type="datetime-local" value={when_} onChange={(e) => setWhen(e.target.value)} />
            <input placeholder="Note to the customer" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <div className="actions">
            {NEXT[s.status].map((st) => (
              <button key={st} className={st === "CONFIRMED" ? "primary" : st === "CANCELLED" ? "danger-outline" : ""} onClick={() => update(st)}>
                {st === "CONFIRMED" ? "Confirm appointment" : st.replace(/_/g, " ").toLowerCase()}
              </button>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}
