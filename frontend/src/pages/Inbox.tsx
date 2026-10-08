import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { TierBadge } from "../components/trace";
import { Card, Empty, ErrorBanner, when } from "../components/ui";
import { useAsync } from "../components/useAsync";
import type { OwnerMessage, ReplyWithContext } from "../types";
import Replies from "./Replies";

export default function Inbox() {
  const [tab, setTab] = useState<"customers" | "prospects">("customers");
  return (
    <>
      <h1>Inbox · Email Intelligence</h1>
      <p className="muted page-sub">
        Every incoming message is classified <span className="tier tier-green">GREEN routine</span>{" "}
        <span className="tier tier-yellow">YELLOW opportunity</span>{" "}
        <span className="tier tier-red">RED human attention</span>. Backend rules pick the tier from what was detected; the AI cannot downgrade it.
      </p>
      <div className="tabs">
        <button className={tab === "customers" ? "active" : ""} onClick={() => setTab("customers")}>Customer messages</button>
        <button className={tab === "prospects" ? "active" : ""} onClick={() => setTab("prospects")}>Prospect replies</button>
      </div>
      {tab === "customers" ? <CustomerMessages /> : <ProspectReplies />}
    </>
  );
}

function ProspectReplies() {
  // Reuse the existing explainable reply view, plus a tier summary.
  const replies = useAsync(() => api.get<(ReplyWithContext & { tier?: string })[]>("/replies"));
  return replies.error ? <ErrorBanner error={replies.error} /> : <Replies embedded />;
}

function CustomerMessages() {
  const inbox = useAsync(() => api.get<OwnerMessage[]>("/inbox"));
  const [tier, setTier] = useState("");
  // Business conversations only (Product Support AI chats are a separate channel).
  const business = (inbox.data ?? []).filter((m) => m.channel === "business");
  const rows = business.filter((m) => m.sender === "customer" && (!tier || m.tier === tier));
  // The response to a customer message is the next message in that conversation, if it isn't from the customer.
  const answeredBy = new Map<string, OwnerMessage>();
  const chrono = [...business].sort((a, b) => a.created_at.localeCompare(b.created_at));
  chrono.forEach((m, i) => {
    const next = chrono.slice(i + 1).find((n) => n.customer_id === m.customer_id);
    if (m.sender === "customer" && next && next.sender !== "customer") answeredBy.set(m.id, next);
  });
  return (
    <>
      <div className="actions" style={{ marginBottom: 12 }}>
        {["", "RED", "YELLOW", "GREEN"].map((t) => (
          <button key={t} className={tier === t ? "primary" : ""} onClick={() => setTier(t)}>{t || "All"}</button>
        ))}
      </div>
      <ErrorBanner error={inbox.error} />
      {rows.length === 0 && <Card><Empty>No customer messages.</Empty></Card>}
      {rows.map((m) => {
        const a = m.analysis as { summary?: string; reason?: string; recommended_action?: string; suggested_response?: string; escalated?: boolean; evidence?: Record<string, string> };
        return (
          <section key={m.id} className={`card reply-card cls-${m.tier === "RED" ? "UNSUBSCRIBE" : m.tier === "YELLOW" ? "ASKED_QUESTION" : "INTERESTED"}`}>
            <header className="reply-card-head">
              <div className="reply-class">
                <TierBadge tier={m.tier} />
                {m.handled_automatically && <span className="badge good">auto-handled</span>}
                {a.escalated && <span className="badge warn">escalated to you</span>}
              </div>
              <div className="actions">
                <span className="muted small">{when(m.created_at)}</span>
                <Link to={`/customers/${m.customer_id}`}>{m.customer_name} →</Link>
              </div>
            </header>
            <blockquote>{m.body}</blockquote>
            <div className="grid-3 reply-explain">
              <div>
                <h3>Detected</h3>
                {m.intents.length ? (
                  <ul className="checklist">
                    {m.intents.map((i) => <li key={i} className="pass"><span>✓</span> {i.replace(/_/g, " ")}{a.evidence?.[i] && a.evidence[i] !== "question" && <span className="reason"> — “{a.evidence[i]}”</span>}</li>)}
                  </ul>
                ) : <p className="muted small">No specific intent detected.</p>}
                {a.summary && <p className="small">{a.summary}</p>}
              </div>
              <div>
                <h3>Why this tier</h3>
                <p className="small">{a.reason ?? "—"}</p>
                <p className="muted small">Confidence: not reported (tiers come from rules, not model confidence)</p>
              </div>
              <div>
                <h3>Action</h3>
                {a.recommended_action && <p className="small">→ {a.recommended_action}</p>}
                {answeredBy.get(m.id) && (() => {
                  const r = answeredBy.get(m.id)!;
                  return <p className="small"><b>{r.sender === "ai" ? "AI replied (from documentation)" : "You replied"}:</b> {r.body.slice(0, 160)}{r.body.length > 160 ? "…" : ""}</p>;
                })()}
                {!answeredBy.get(m.id) && a.escalated && <p className="small muted">Waiting for your response in Approvals.</p>}
              </div>
            </div>
          </section>
        );
      })}
    </>
  );
}
