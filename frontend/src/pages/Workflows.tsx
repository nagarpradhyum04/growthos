import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, describeError } from "../api";
import { timeAgo } from "../components/agents";
import { OrchestrationFlow, TraceFeed, workflowStages } from "../components/trace";
import { Badge, Card, Empty, ErrorBanner, Stat } from "../components/ui";
import { useAsync } from "../components/useAsync";
import type { ApprovalItem, SystemStatus, WorkflowDetail, WorkflowSummary } from "../types";

const TERMINAL = ["COMPLETED", "BLOCKED", "FAILED"];
const STATE_TONE: Record<string, string> = {
  COMPLETED: "good", AWAITING_APPROVAL: "warn", ESCALATED: "warn", BLOCKED: "bad", FAILED: "bad",
  WAITING_FOR_REPLY: "info",
};

export function StateBadge({ state }: { state: string }) {
  return <span className={`badge ${STATE_TONE[state] ?? "info"}`}>{state.replace(/_/g, " ")}</span>;
}

export default function Workflows() {
  const [type, setType] = useState("GOAL");
  const list = useAsync(() => api.get<WorkflowSummary[]>(`/workflows?top_level=${type === "GOAL"}${type ? `&workflow_type=${type}` : ""}&limit=100`), [type]);
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Workflows &amp; Agent Trace</h1>
          <p className="muted page-sub">Every orchestrated run, its state machine and the step-by-step trace of which agent did what.</p>
        </div>
        <select value={type} onChange={(e) => setType(e.target.value)}>
          <option value="GOAL">Business goals</option>
          <option value="LEAD">Lead journeys</option>
          <option value="INBOUND">Inbound (messages, support, warranty)</option>
          <option value="LIFECYCLE">Lifecycle follow-ups</option>
          <option value="">All</option>
        </select>
      </div>
      <ErrorBanner error={list.error} />
      <Card>
        {list.data?.length === 0 && <Empty>No workflows yet. Give GrowthOS a goal from the Command Center.</Empty>}
        {!!list.data?.length && (
          <table>
            <thead><tr><th>Workflow</th><th>Type</th><th>State</th><th>Summary</th><th>Updated</th></tr></thead>
            <tbody>
              {list.data.map((w) => (
                <tr key={w.id}>
                  <td><Link to={`/workflows/${w.id}`}>{w.company_name ?? w.goal}</Link></td>
                  <td className="small">{w.type}</td>
                  <td><StateBadge state={w.state} /></td>
                  <td className="small muted">{Object.entries(w.summary).filter(([, v]) => v).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ") || "—"}</td>
                  <td className="small muted">{timeAgo(w.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}

export function WorkflowView() {
  const { id } = useParams();
  const [wf, setWf] = useState<WorkflowDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const load = async () => {
      try {
        const data = await api.get<WorkflowDetail>(`/workflows/${id}`);
        if (!alive) return;
        setWf(data);
        const running = !TERMINAL.includes(data.state) && !["AWAITING_APPROVAL", "WAITING_FOR_REPLY", "ESCALATED"].includes(data.state);
        if (running) timer = window.setTimeout(load, 1000);
      } catch (err) {
        if (alive) setError(String(err));
      }
    };
    void load();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [id]);

  if (error) return <ErrorBanner error={error} />;
  if (!wf) return <p className="muted">Loading…</p>;
  const live = !TERMINAL.includes(wf.state) && !["AWAITING_APPROVAL", "WAITING_FOR_REPLY", "ESCALATED"].includes(wf.state);
  const s = wf.summary;
  return (
    <>
      <div className="page-header">
        <div>
          <div className="muted small"><Link to="/workflows">Workflows</Link> / {wf.type}</div>
          <h1>{wf.company_name ?? wf.goal} <StateBadge state={wf.state} />{live && <span className="live-dot">Live</span>}</h1>
          {wf.error && <p className="banner error"><span>{wf.error}</span></p>}
        </div>
        {wf.lead_id && <Link className="button" to={`/leads/${wf.lead_id}`}>Open lead →</Link>}
      </div>
      <OrchestrationFlow events={[...wf.events, ...(wf.sub_events ?? [])]} state={wf.state} title="Orchestration — agents in this run"
        only={workflowStages(wf, [...wf.events, ...(wf.sub_events ?? [])])} />
      {wf.command === "social" && Object.keys(s).length > 0 && (
        <div className="stats">
          <Stat label="Week of" value={s.week_start ? new Date(`${s.week_start}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "—"} />
          <Stat label="Posts ready" value={s.generated ?? 0} hint="waiting for your approval" />
          <Stat label="Flagged by rules" value={s.flagged ?? 0} />
          <Stat label="Media failed" value={s.failed ?? 0} />
        </div>
      )}
      {wf.type === "GOAL" && (!wf.command || wf.command === "acquire") && Object.keys(s).length > 0 && (
        <div className="stats">
          <Stat label="Prospects" value={s.leads ?? 0} />
          <Stat label="Researched" value={s.researched ?? 0} />
          <Stat label="Qualified" value={s.qualified ?? 0} hint={`${s.disqualified ?? 0} not qualified`} />
          <Stat label="Drafts" value={s.drafted ?? 0} />
          <Stat label="Safety" value={`${s.safety_passed ?? 0} ✓`} hint={`${s.safety_escalated ?? 0} escalated · ${s.safety_blocked ?? 0} blocked`} />
          <Stat label="Awaiting you" value={s.awaiting_approval ?? 0} hint="human approvals" />
        </div>
      )}
      <DraftsToSend wf={wf} />
      <div className="grid-main">
        <Card title="Agent trace" actions={<span className="muted small">{wf.events.length} recorded events</span>}>
          <TraceFeed events={wf.events} />
        </Card>
        <div>
          {wf.children.length > 0 && (
            <Card title={wf.command === "full_cycle" ? "Stages" : "Lead workflows"} actions={<Link to="/approvals">Pending approvals →</Link>}>
              <ul className="list">
                {wf.children.map((c) => (
                  <li key={c.id}>
                    <Link to={`/workflows/${c.id}`}>{c.company_name ?? c.goal}</Link>
                    <StateBadge state={c.state} />
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <Card title="Plan">
            <ol className="plan">{wf.plan.map((p) => <li key={p}>{p.replace(/_/g, " ")}</li>)}</ol>
            <p className="muted small">Routing between steps is deterministic: the Orchestrator never asks an LLM what to do next.</p>
          </Card>
          {wf.parent_id && <p className="small"><Link to={`/workflows/${wf.parent_id}`}>← Parent goal workflow</Link></p>}
          <p className="muted small">Started {new Date(wf.created_at).toLocaleString()} <Badge value={wf.type} /></p>
        </div>
      </div>
    </>
  );
}

/** Emails the Outreach Agent drafted in this run. First-touch emails always need the owner's approval;
 * approving here sends through the same backend path (can_send() still checks every rule). */
function DraftsToSend({ wf }: { wf: WorkflowDetail }) {
  const leadIds = new Set([...wf.children.map((c) => c.lead_id), ...(wf.sub_events ?? []).map((e) => e.lead_id), wf.lead_id]
    .filter((x): x is string => !!x));
  const approvals = useAsync(() => api.get<ApprovalItem[]>("/approvals?status=PENDING"), [wf.id, wf.state]);
  const status = useAsync(() => api.get<SystemStatus>("/system/status"));
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Record<string, string>>({});
  if (!leadIds.size) return null;
  const drafts = (approvals.data ?? []).filter((a) => a.type === "OUTBOUND_EMAIL" && a.lead_id && leadIds.has(a.lead_id));
  const sentHere = Object.values(results).filter((r) => r === "Sent").length;
  if (!drafts.length && !sentHere) return null;

  async function send(items: ApprovalItem[]) {
    setBusy(true);
    for (const a of items) {
      try {
        await api.post(`/approvals/${a.id}/approve`, { send: true, note: "Approved from the run summary" });
        setResults((r) => ({ ...r, [a.id]: "Sent" }));
      } catch (err) {
        setResults((r) => ({ ...r, [a.id]: describeError(err) }));
      }
    }
    setBusy(false);
    approvals.reload();
  }

  const mock = status.data?.providers.email === "mock";
  return (
    <Card title={`Emails ready to send (${drafts.length})`} actions={drafts.length > 1 ? (
      <button className="primary" disabled={busy} onClick={() => {
        if (window.confirm(`Send ${drafts.length} first-touch emails now? Each one still passes the safety checks.`)) void send(drafts);
      }}>Approve &amp; send all ({drafts.length})</button>) : undefined}>
      <p className="muted small" style={{ marginTop: 0 }}>
        The Outreach Agent wrote these and the Safety Agent passed them. First emails to new prospects are never sent without
        your approval. Read each one (or edit it) before sending.
        {mock && <> <b>Email is in mock mode:</b> “sent” emails are recorded but not delivered. Set <code>EMAIL_PROVIDER=resend</code> to deliver real email.</>}
      </p>
      <ErrorBanner error={approvals.error} />
      <table>
        <tbody>
          {drafts.map((a) => (
            <tr key={a.id}>
              <td><b>{a.company_name}</b><div className="muted small">{String(a.subject.subject ?? "")}</div></td>
              <td className="small">{results[a.id] && <span className="banner error small">{results[a.id]}</span>}</td>
              <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                {typeof a.subject.id === "string" && <Link className="button" to={`/emails/${a.subject.id}`}>Review / edit</Link>}{" "}
                <button className="primary" disabled={busy} onClick={() => void send([a])}>Approve &amp; send</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {sentHere > 0 && <p className="banner ok small"><span>{sentHere} email(s) sent{mock ? " (mock — not delivered)" : ""}. Replies and follow-ups are tracked automatically.</span></p>}
    </Card>
  );
}
