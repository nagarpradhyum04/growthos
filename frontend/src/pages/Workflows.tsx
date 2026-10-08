import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { timeAgo } from "../components/agents";
import { OrchestrationFlow, TraceFeed } from "../components/trace";
import { Badge, Card, Empty, ErrorBanner, Stat } from "../components/ui";
import { useAsync } from "../components/useAsync";
import type { WorkflowDetail, WorkflowSummary } from "../types";

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
      <OrchestrationFlow events={wf.events} state={wf.state} title="Orchestration — from goal to memory" />
      {wf.type === "GOAL" && Object.keys(s).length > 0 && (
        <div className="stats">
          <Stat label="Prospects" value={s.leads ?? 0} />
          <Stat label="Researched" value={s.researched ?? 0} />
          <Stat label="Qualified" value={s.qualified ?? 0} hint={`${s.disqualified ?? 0} not qualified`} />
          <Stat label="Drafts" value={s.drafted ?? 0} />
          <Stat label="Safety" value={`${s.safety_passed ?? 0} ✓`} hint={`${s.safety_escalated ?? 0} escalated · ${s.safety_blocked ?? 0} blocked`} />
          <Stat label="Awaiting you" value={s.awaiting_approval ?? 0} hint="human approvals" />
        </div>
      )}
      <div className="grid-main">
        <Card title="Agent trace" actions={<span className="muted small">{wf.events.length} recorded events</span>}>
          <TraceFeed events={wf.events} />
        </Card>
        <div>
          {wf.children.length > 0 && (
            <Card title="Lead workflows" actions={<Link to="/approvals">Pending approvals →</Link>}>
              <ul className="list">
                {wf.children.map((c) => (
                  <li key={c.id}>
                    <Link to={`/workflows/${c.id}`}>{c.company_name}</Link>
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
