import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { TierBadge } from "../components/trace";
import { Badge, Card, Empty, ErrorBanner, when } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { ReplyWithContext } from "../types";

const CLASSES = ["INTERESTED", "ASKED_QUESTION", "REQUESTED_LATER", "NOT_INTERESTED", "UNSUBSCRIBE", "OUT_OF_OFFICE", "UNKNOWN"];

const MEANING: Record<string, string> = {
  INTERESTED: "Positive intent — the contact wants to continue the conversation",
  ASKED_QUESTION: "The contact asked something that needs an answer",
  REQUESTED_LATER: "The contact asked to be contacted at a later time",
  NOT_INTERESTED: "The contact declined",
  UNSUBSCRIBE: "The contact asked not to be contacted again",
  OUT_OF_OFFICE: "Automatic away / out-of-office reply",
  UNKNOWN: "Unclear — a human should read it",
};

export default function Replies({ embedded = false }: { embedded?: boolean }) {
  const [filter, setFilter] = useState("");
  const replies = useAsync(
    () => api.get<ReplyWithContext[]>(`/replies${filter === "attention" ? "?needs_attention=true" : filter ? `?classification=${filter}` : ""}`),
    [filter],
  );
  const action = useAction();

  async function analyze(id: string) {
    await action.run("analyze", () => api.post(`/replies/${id}/analyze`));
    replies.reload();
  }

  return (
    <>
      <div className="page-header">
        <div>
          {!embedded && <h1>Replies</h1>}
          <p className="muted page-sub">Backend rules act first (any reply stops follow-ups; opt-out language suppresses instantly). The Reply Analysis Agent then classifies and recommends.</p>
        </div>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All replies</option>
          <option value="attention">Needs attention</option>
          {CLASSES.map((c) => <option key={c} value={c}>{c === "UNSUBSCRIBE" ? "OPT OUT" : c.replace(/_/g, " ")}</option>)}
        </select>
      </div>
      <ErrorBanner error={replies.error ?? action.error} />
      {replies.data?.length === 0 && <Card><Empty>No replies yet. Log one from a lead page or connect the inbound webhook.</Empty></Card>}
      {replies.data?.map((r) => <ReplyCard key={r.id} r={r} analyzing={!!action.busy} onAnalyze={() => analyze(r.id)} />)}
    </>
  );
}

function ReplyCard({ r, analyzing, onAnalyze }: { r: ReplyWithContext; analyzing: boolean; onAnalyze: () => void }) {
  const cls = r.classification;
  const ext = r as ReplyWithContext & { tier?: string | null; escalation_reason?: string | null; suggested_response?: string | null };
  const byAgent = !!r.agent_run_id;
  const detected: { ok: boolean; text: string }[] = [];
  if (cls) detected.push({ ok: true, text: MEANING[cls] ?? cls });
  detected.push(
    r.opt_out_detected
      ? { ok: true, text: "Explicit opt-out language (deterministic rule, before the AI)" }
      : { ok: true, text: "No opt-out language found by the deterministic rule" },
  );
  if (cls) detected.push({ ok: true, text: byAgent ? "Classified by the Reply Analysis Agent" : "Classified by backend rules (no AI needed)" });

  const actions: string[] = [];
  if (r.followups_cancelled > 0) actions.push(`Automated follow-ups stopped (${r.followups_cancelled} cancelled)`);
  if (r.followups_pending > 0) actions.push(`${r.followups_pending} follow-up(s) still pending`);
  if (r.contact_suppressed) actions.push("Contact suppressed — all future outreach blocked");
  if (r.contact_forgotten) actions.push("Forget Me applied — personal data erased");
  if (r.requires_human_attention) actions.push("Human response required");

  return (
    <section className={`card reply-card cls-${cls ?? "pending"}`}>
      <header className="reply-card-head">
        <div className="reply-class">
          <Badge value={cls ?? "PENDING"} />
          <TierBadge tier={ext.tier} />
          <span className="muted small">Confidence: not reported by the agent</span>
        </div>
        <div className="actions">
          <span className="muted small">{when(r.received_at)}</span>
          <Link to={`/leads/${r.lead_id}`}>{r.company_name} →</Link>
        </div>
      </header>
      <blockquote>{r.body}</blockquote>
      {!r.analyzed_at ? (
        <div className="actions"><span className="muted small">Analysis queued for the worker.</span><button disabled={analyzing} onClick={onAnalyze}>Analyze now</button></div>
      ) : (
        <div className="grid-3 reply-explain">
          <div>
            <h3>Detected</h3>
            <ul className="checklist">{detected.map((d) => <li key={d.text} className="pass"><span>✓</span> {d.text}</li>)}</ul>
            {r.summary && <p className="small">{r.summary}</p>}
          </div>
          <div>
            <h3>Recommended</h3>
            <ul className="arrows">{r.recommended_action ? <li>→ {r.recommended_action}</li> : <li className="muted">—</li>}</ul>
            {ext.escalation_reason && <p className="small"><b>Tier reason:</b> {ext.escalation_reason}</p>}
            {ext.suggested_response && <p className="small"><b>Suggested reply:</b> {ext.suggested_response}</p>}
          </div>
          <div>
            <h3>Actions taken by backend</h3>
            {actions.length ? <ul className="arrows">{actions.map((a) => <li key={a}>→ {a}</li>)}</ul> : <p className="muted small">None needed.</p>}
          </div>
        </div>
      )}
    </section>
  );
}
