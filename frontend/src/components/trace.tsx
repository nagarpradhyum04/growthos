// Agent trace UI built only from recorded workflow events (never simulated).
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, describeError } from "../api";
import type { ApprovalItem, TraceEvent } from "../types";
import { fmtDuration, timeAgo } from "./agents";
import { Badge } from "./ui";

export const TRACE_AGENTS: Record<string, { label: string; kind: "agent" | "human" | "rule" | "system" }> = {
  orchestrator: { label: "Orchestrator", kind: "system" },
  research: { label: "Research Agent", kind: "agent" },
  qualification: { label: "Qualification Agent", kind: "agent" },
  memory: { label: "Shared Memory", kind: "system" },
  outreach: { label: "Outreach Agent", kind: "agent" },
  safety: { label: "Safety Agent", kind: "rule" },
  human: { label: "Human Review", kind: "human" },
  email_intelligence: { label: "Email Intelligence", kind: "agent" },
  followup: { label: "Follow-up Agent", kind: "agent" },
  analytics: { label: "Analytics Agent", kind: "agent" },
  support: { label: "Product Support AI", kind: "agent" },
  warranty: { label: "Warranty check", kind: "rule" },
  access: { label: "Access Agent", kind: "rule" },
  system: { label: "System", kind: "system" },
};

const STATUS_PILL: Record<string, string> = {
  COMPLETED: "completed", SKIPPED: "pending", WAITING: "waiting", ESCALATED: "waiting", BLOCKED: "blocked",
  FAILED: "blocked", RETRYING: "running", STARTED: "running",
};

export function agentLabel(agent: string) {
  return TRACE_AGENTS[agent]?.label ?? agent;
}

export function TraceFeed({ events, showContext = false, compact = false }: { events: TraceEvent[]; showContext?: boolean; compact?: boolean }) {
  if (!events.length) return <p className="empty">No agent activity recorded yet.</p>;
  return (
    <ol className={`trace ${compact ? "compact" : ""}`}>
      {events.map((e) => {
        const meta = TRACE_AGENTS[e.agent] ?? { label: e.agent, kind: "system" };
        return (
          <li key={e.id} className={`trace-row tr-${e.status.toLowerCase()}`}>
            <span className={`trace-chip kind-${meta.kind}`}>{meta.label}</span>
            <div className="trace-main">
              <div className="trace-action">
                <b>{e.action}</b>
                {showContext && (e.company_name || e.goal) && (
                  <span className="muted small"> · {e.lead_id ? <Link to={`/leads/${e.lead_id}`}>{e.company_name}</Link> : e.goal}</span>
                )}
              </div>
              <div className="trace-result">{e.result}</div>
            </div>
            <div className="trace-meta">
              <span className={`pill pill-${STATUS_PILL[e.status] ?? "pending"}`}>{e.status.replace("_", " ")}</span>
              <span className="muted small">
                {e.duration_ms != null && e.duration_ms > 0 ? `${fmtDuration(e.duration_ms)} · ` : ""}
                {showContext ? timeAgo(e.completed_at ?? e.started_at) : new Date(e.completed_at ?? e.started_at).toLocaleTimeString()}
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// Orchestration flow: one node per stage; state = latest recorded event for that stage.
const FLOW: { key: string; label: string; agents: string[]; kind: string; match?: (e: TraceEvent) => boolean }[] = [
  { key: "orchestrator", label: "Orchestrator", agents: ["orchestrator"], kind: "system" },
  { key: "research", label: "Research", agents: ["research"], kind: "agent" },
  { key: "qualification", label: "Qualification", agents: ["qualification"], kind: "agent" },
  { key: "outreach", label: "Outreach", agents: ["outreach"], kind: "agent" },
  { key: "safety", label: "Safety", agents: ["safety"], kind: "rule", match: (e) => !e.action.startsWith("Send gate") },
  { key: "human", label: "Human / Automation", agents: ["human"], kind: "human" },
  { key: "send", label: "Send", agents: ["safety"], kind: "rule", match: (e) => e.action.startsWith("Send gate") },
  { key: "email_intelligence", label: "Email Intelligence", agents: ["email_intelligence"], kind: "agent" },
  { key: "followup", label: "Follow-up", agents: ["followup"], kind: "agent" },
  { key: "analytics", label: "Analytics", agents: ["analytics"], kind: "agent" },
  { key: "memory", label: "Memory", agents: ["memory"], kind: "system" },
];

const STATE_STAGE: Record<string, string> = {
  PENDING: "orchestrator", RESEARCHING: "research", QUALIFYING: "qualification", DRAFTING: "outreach",
  SAFETY_CHECK: "safety", AWAITING_APPROVAL: "human", READY_TO_SEND: "send", SENT: "send",
  WAITING_FOR_REPLY: "email_intelligence", REPLY_RECEIVED: "email_intelligence", ESCALATED: "human",
  FOLLOW_UP_SCHEDULED: "followup",
};

const FLOW_STATE: Record<string, string> = {
  COMPLETED: "completed", SKIPPED: "completed", WAITING: "waiting", ESCALATED: "waiting", BLOCKED: "blocked",
  FAILED: "failed", RETRYING: "running", STARTED: "running",
};

export function OrchestrationFlow({ events, state, title = "Orchestration workflow", only }: {
  events: TraceEvent[]; state?: string; title?: string; only?: string[];
}) {
  const current = state ? STATE_STAGE[state] : undefined;
  const stages = FLOW.filter((s) => !only || only.includes(s.key)).map((s) => {
    const mine = events.filter((e) => s.agents.includes(e.agent) && (!s.match || s.match(e)));
    const last = mine[mine.length - 1];
    let st = last ? FLOW_STATE[last.status] ?? "completed" : "pending";
    if (s.key === current && st !== "blocked" && st !== "failed" && state && !["COMPLETED", "BLOCKED", "FAILED"].includes(state)) {
      st = st === "completed" && ["SENT"].includes(state) ? "completed" : st === "pending" ? "running" : st;
    }
    return { ...s, st, result: last?.result ?? "Not started", count: mine.length };
  });
  return (
    <section className="card">
      <header className="card-header">
        <h2>{title}</h2>
        <div className="legend small">
          {["completed", "running", "waiting", "blocked", "failed", "pending"].map((k) => (
            <span key={k}><i className={`dot dot-${k}`} />{k === "pending" ? "pending" : k}</span>
          ))}
        </div>
      </header>
      <div className="workflow">
        {stages.map((s, i) => (
          <div key={s.key} className="wf-step">
            <div className={`wf-node wf-${s.st === "failed" ? "blocked" : s.st === "running" ? "running" : s.st} kind-${s.kind === "system" ? "rule" : s.kind} ${s.key === current ? "wf-current" : ""}`} title={s.result}>
              <div className="wf-kind">{s.kind === "agent" ? "AI agent" : s.kind === "human" ? "Human" : s.kind === "rule" ? "Rule" : "Core"}</div>
              <div className="wf-name">{s.label}</div>
              <div className="wf-state">{s.st === "pending" ? "Pending" : s.st[0].toUpperCase() + s.st.slice(1)}{s.key === current ? " · now" : ""}</div>
            </div>
            {i < stages.length - 1 && <div className={`wf-arrow ${s.st === "completed" ? "done" : ""}`} aria-hidden>→</div>}
          </div>
        ))}
      </div>
    </section>
  );
}

export function TierBadge({ tier }: { tier: string | null | undefined }) {
  if (!tier) return null;
  const label = { GREEN: "Routine", YELLOW: "Opportunity", RED: "Human attention" }[tier] ?? tier;
  return <span className={`tier tier-${tier.toLowerCase()}`}>{tier} · {label}</span>;
}

const TYPE_LABEL: Record<string, string> = {
  OUTBOUND_EMAIL: "Outbound email", REPLY_ESCALATION: "Prospect reply", MESSAGE_ESCALATION: "Customer message",
  WARRANTY_CLAIM: "Warranty claim", SERVICE_REQUEST: "Service request",
};

/** One pending human decision with real backend actions. */
export function ApprovalCard({ item, onDone }: { item: ApprovalItem; onDone: () => void }) {
  const [response, setResponse] = useState(item.suggested_response);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const subj = item.subject as Record<string, string | string[] | undefined>;

  async function act(action: string, body: Record<string, unknown> = {}) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/approvals/${item.id}/${action}`, { note, response, ...body });
      onDone();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  const pending = item.status === "PENDING";
  return (
    <article className={`approval-card prio-${item.priority.toLowerCase()}`}>
      <header className="approval-head">
        <div>
          <div className="approval-meta">
            <span className={`prio prio-${item.priority.toLowerCase()}`}>{item.priority}</span>
            <span className="muted small">{TYPE_LABEL[item.type]}</span>
            <TierBadge tier={item.tier} />
          </div>
          <h3 className="approval-title">{item.title}</h3>
        </div>
        <span className="muted small">{timeAgo(item.created_at)}</span>
      </header>
      <p className="approval-reason"><b>Why:</b> {item.reason}</p>
      {typeof subj.body === "string" && <blockquote className="clamp">{subj.body}</blockquote>}
      {typeof subj.issue === "string" && <blockquote>{subj.issue}</blockquote>}
      {item.recommended_action && <p className="small"><b>Recommended:</b> → {item.recommended_action}</p>}
      {pending && item.type === "MESSAGE_ESCALATION" && (
        <label className="small">Response to the customer (AI suggestion — edit before sending)
          <textarea rows={3} value={response} onChange={(e) => setResponse(e.target.value)} />
        </label>
      )}
      {pending && item.type === "REPLY_ESCALATION" && item.suggested_response && (
        <div className="suggested"><span className="muted small">Suggested reply (send from your own inbox):</span><p>{item.suggested_response}</p></div>
      )}
      {error && <div className="banner error"><span>{error}</span></div>}
      {pending ? (
        <div className="actions approval-actions">
          {item.type === "OUTBOUND_EMAIL" && <>
            <button className="primary" disabled={busy} onClick={() => act("approve", { send: true })}>Approve &amp; send</button>
            {typeof subj.id === "string" && <Link className="button" to={`/emails/${subj.id}`}>Edit</Link>}
          </>}
          {item.type === "MESSAGE_ESCALATION" && <button className="primary" disabled={busy || !response.trim()} onClick={() => act("approve")}>Send response</button>}
          {item.type === "REPLY_ESCALATION" && <button className="primary" disabled={busy} onClick={() => act("approve", { note: note || "Handled by owner" })}>Mark handled</button>}
          {item.type === "WARRANTY_CLAIM" && <button className="primary" disabled={busy} onClick={() => act("approve", { note: note || "Approved" })}>Approve claim</button>}
          {item.type === "SERVICE_REQUEST" && <Link className="button primary-outline" to="/care">Schedule →</Link>}
          <button className="danger-outline" disabled={busy} onClick={() => act("reject", { note: note || (item.type === "WARRANTY_CLAIM" ? "" : "Rejected") })}>Reject</button>
          <button disabled={busy} onClick={() => act("take-over")}>Take over</button>
          {item.can_automate && <button className="link" disabled={busy} onClick={() => act("mark-automated")} title="Resolve and automate this category in future">Mark as automated</button>}
          <input className="note-input" placeholder="Note (optional; required to reject a warranty claim)" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
      ) : (
        <p className="small muted"><Badge value={item.status} /> {item.resolution_note}</p>
      )}
      <div className="approval-links small">
        {item.lead_id && <Link to={`/leads/${item.lead_id}`}>{item.company_name ?? "Lead"} →</Link>}
        {item.customer_id && <Link to={`/customers/${item.customer_id}`}>{item.customer_name ?? "Customer"} →</Link>}
        {item.workflow_id && <Link to={`/workflows/${item.workflow_id}`}>Agent trace →</Link>}
      </div>
    </article>
  );
}
