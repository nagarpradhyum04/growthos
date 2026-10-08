import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { timeAgo } from "../components/agents";
import { ApprovalCard, TRACE_AGENTS, TraceFeed } from "../components/trace";
import { Badge, Card, Empty, ErrorBanner, Stat, pct } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { Analytics, ApprovalItem, Campaign, TraceEvent, WorkflowSummary } from "../types";

const STATUS_AGENTS = ["orchestrator", "research", "qualification", "outreach", "safety", "email_intelligence",
  "followup", "analytics", "support", "memory"];

function agentState(events: TraceEvent[]): { label: string; tone: string; last?: TraceEvent } {
  const last = events[0];
  if (!last) return { label: "Idle", tone: "pending" };
  if (last.status === "FAILED") return { label: "Failed", tone: "blocked", last };
  if (last.status === "BLOCKED") return { label: "Blocked", tone: "blocked", last };
  if (last.status === "WAITING" || last.status === "ESCALATED") return { label: "Waiting", tone: "waiting", last };
  if (last.status === "RETRYING" || last.status === "STARTED") return { label: "Running", tone: "running", last };
  return { label: "Operational", tone: "completed", last };
}

export default function Dashboard() {
  const analytics = useAsync(() => api.get<Analytics>("/analytics"));
  const trace = useAsync(() => api.get<TraceEvent[]>("/trace?limit=200"));
  const approvals = useAsync(() => api.get<ApprovalItem[]>("/approvals?status=PENDING"));
  const campaigns = useAsync(() => api.get<Campaign[]>("/campaigns"));
  const goals = useAsync(() => api.get<WorkflowSummary[]>("/workflows?workflow_type=GOAL&top_level=true&limit=3"));
  const m = analytics.data?.overall;
  const lc = analytics.data?.lifecycle;

  function reloadAll() {
    approvals.reload();
    trace.reload();
    analytics.reload();
  }

  return (
    <>
      <h1>GrowthOS Command Center</h1>
      <p className="muted page-sub">AI handles the routine and surfaces what's important. You make the important decisions.</p>
      <ErrorBanner error={analytics.error ?? trace.error ?? approvals.error} />

      <GoalLauncher campaigns={campaigns.data ?? []} />

      {m && lc && (
        <div className="stats">
          <Stat label="Total leads" value={m.leads_total} />
          <Stat label="Qualified leads" value={m.leads_qualified} hint={`${m.leads_disqualified} not contacted`} />
          <Stat label="Active campaigns" value={m.active_campaigns} />
          <Stat label="Pending approvals" value={m.pending_approvals} hint="need your decision" />
          <Stat label="Customers" value={lc.customers} hint={`${m.conversions} converted from outreach`} />
          <Stat label="Open opportunities" value={m.open_opportunities} hint="YELLOW escalations" />
          <Stat label="Reply rate" value={pct(m.reply_rate_pct)} hint={`${m.emails_sent} emails sent`} />
          <Stat label="Conversion rate" value={pct(m.leads_total ? Math.round((m.conversions / m.leads_total) * 1000) / 10 : null)} hint="leads → customers" />
        </div>
      )}

      <div className="grid-main">
        <div>
          <Card title="Pending human actions" actions={<Link to="/approvals">All ({approvals.data?.length ?? 0}) →</Link>}>
            {approvals.data?.length === 0 && <Empty>Nothing needs you right now.</Empty>}
            <div className="approval-grid single">
              {approvals.data?.slice(0, 3).map((a) => <ApprovalCard key={a.id} item={a} onDone={reloadAll} />)}
            </div>
          </Card>
          <Card title="Recent agent activity" actions={<Link to="/workflows">Workflows →</Link>}>
            <TraceFeed events={(trace.data ?? []).slice(0, 12)} showContext compact />
          </Card>
        </div>
        <div>
          <Card title="Agent status" actions={<span className="muted small">from the agent trace</span>}>
            <ul className="agent-status-list">
              {STATUS_AGENTS.map((key) => {
                const st = agentState((trace.data ?? []).filter((e) => e.agent === key));
                return (
                  <li key={key}>
                    <span className={`status-dot sd-${st.tone}`} />
                    <div>
                      <b>{TRACE_AGENTS[key].label}</b>
                      <div className="muted small">{st.last ? `${st.last.action} · ${timeAgo(st.last.completed_at ?? st.last.started_at)}` : "No activity yet"}</div>
                    </div>
                    <span className={`pill pill-${st.tone}`}>{st.label}</span>
                  </li>
                );
              })}
            </ul>
          </Card>
          <Card title="Recent goals">
            {goals.data?.length === 0 && <Empty>No goals yet.</Empty>}
            <ul className="list">
              {goals.data?.map((g) => (
                <li key={g.id}><Link to={`/workflows/${g.id}`}>{g.goal}</Link><Badge value={g.state === "AWAITING_APPROVAL" ? "WAITING" : g.state} /></li>
              ))}
            </ul>
          </Card>
          <Card title="Campaigns" actions={<Link to="/campaigns">Manage →</Link>}>
            <table>
              <tbody>
                {analytics.data?.campaigns.map((c) => (
                  <tr key={c.campaign_id}>
                    <td>{c.name}</td>
                    <td><Badge value={c.status} /></td>
                    <td className="muted small">{c.leads_total} leads · {c.emails_sent} sent · {c.replies} replies</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      </div>
    </>
  );
}

function GoalLauncher({ campaigns }: { campaigns: Campaign[] }) {
  const [goal, setGoal] = useState("Find high-quality customers for our business");
  const [campaignId, setCampaignId] = useState("");
  const action = useAction();
  const navigate = useNavigate();
  const selected = campaignId || campaigns.find((c) => c.status === "ACTIVE")?.id || "";

  async function submit(e: FormEvent) {
    e.preventDefault();
    const wf = await action.run("goal", () => api.post<WorkflowSummary>("/workflows/goal", { goal, campaign_id: selected }));
    if (wf) navigate(`/workflows/${wf.id}`);
  }

  return (
    <form className="card goal-launcher" onSubmit={submit}>
      <div className="goal-label">
        <span className="kind-chip agent">Orchestrator</span>
        <b>Give GrowthOS a goal</b>
        <span className="muted small">The Orchestrator plans it, runs the specialist agents on the campaign's prospects, and brings you only the decisions that need a human.</span>
      </div>
      <div className="goal-row">
        <input value={goal} onChange={(e) => setGoal(e.target.value)} required />
        <select value={selected} onChange={(e) => setCampaignId(e.target.value)} required>
          {campaigns.length === 0 && <option value="">Create a campaign first</option>}
          {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.leads} prospects)</option>)}
        </select>
        <button className="primary" disabled={!!action.busy || !selected}>{action.busy ? "Starting…" : "▶ Run"}</button>
      </div>
      <ErrorBanner error={action.error} />
    </form>
  );
}
