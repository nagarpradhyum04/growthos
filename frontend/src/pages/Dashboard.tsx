import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { timeAgo } from "../components/agents";
import { ApprovalCard, TRACE_AGENTS, TraceFeed } from "../components/trace";
import { Badge, Card, Empty, ErrorBanner, Stat, pct } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { Analytics, ApprovalItem, Campaign, SocialPost, SystemStatus, TraceEvent, WorkflowSummary } from "../types";

const STATUS_AGENTS = ["orchestrator", "research", "qualification", "outreach", "safety", "email_intelligence",
  "followup", "analytics", "support", "social", "media", "access", "memory"];

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
  const goals = useAsync(() => api.get<WorkflowSummary[]>("/workflows?workflow_type=GOAL&top_level=true&limit=5"));
  const status = useAsync(() => api.get<SystemStatus>("/system/status"));
  const social = useAsync(() => api.get<SocialPost[]>("/social/posts?weeks=1"));
  const m = analytics.data?.overall;
  const lc = analytics.data?.lifecycle;

  const reloadAll = useCallback(() => {
    approvals.reload();
    trace.reload();
    analytics.reload();
    goals.reload();
    status.reload();
    social.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <h1>GrowthOS Command Center</h1>
      <p className="muted page-sub">AI handles the routine and surfaces what's important. You make the important decisions.</p>
      <ErrorBanner error={analytics.error ?? trace.error ?? approvals.error} />

      <GoalLauncher campaigns={campaigns.data ?? []} onLaunched={reloadAll} />

      {m && lc && (
        <div className="stats">
          <Stat label="Qualified leads" value={m.leads_qualified} hint={`${m.leads_disqualified} not contacted`} />
          <Stat label="Total pipeline leads" value={m.leads_total} />
          <Stat label="Active campaigns" value={m.active_campaigns} />
          <Stat label="Pending approvals" value={m.pending_approvals} hint="human decision required" />
          <Stat label="Customers" value={lc.customers} hint={`${m.conversions} converted from outreach`} />
          <Stat label="Open opportunities" value={m.open_opportunities} hint="YELLOW escalations" />
          <Stat label="Reply rate" value={pct(m.reply_rate_pct)} hint={`${m.emails_sent} emails sent`} />
          <Stat label="Conversion rate" value={pct(m.leads_total ? Math.round((m.conversions / m.leads_total) * 1000) / 10 : null)} hint="leads → customers" />
        </div>
      )}

      <Spotlight status={status.data} trace={trace.data ?? []} pending={approvals.data?.length ?? null} />

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
          <Card title="This week on social" actions={<Link to="/social">Social Studio →</Link>}>
            {social.data?.length === 0 && <Empty>No posts for this week yet. Run “Create this week's social media posts”.</Empty>}
            <ul className="list">
              {social.data?.map((p) => (
                <li key={p.id}><span><b>{p.kind === "image" ? "Static post" : "Video post"}</b> <span className="muted small">· {p.theme || "—"}</span></span><Badge value={p.status} /></li>
              ))}
            </ul>
          </Card>
          <Card title="Recent commands">
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

interface CommandInfo { key: string; label: string; description: string; plan: string[]; examples: string[]; needs_campaign: boolean }
interface RoutePreview { command: CommandInfo | null; matched: string[] }

function GoalLauncher({ campaigns, onLaunched }: { campaigns: Campaign[]; onLaunched: () => void }) {
  const commands = useAsync(() => api.get<CommandInfo[]>("/workflows/commands"));
  const [goal, setGoal] = useState("");
  const [preview, setPreview] = useState<RoutePreview | null>(null);
  const [campaignId, setCampaignId] = useState("");
  const [launched, setLaunched] = useState<WorkflowSummary[]>([]);
  const action = useAction();
  const selected = campaignId || campaigns.find((c) => c.status === "ACTIVE")?.id || "";

  // Live, deterministic preview of which workflow the Orchestrator will run.
  useEffect(() => {
    if (goal.trim().length < 3) { setPreview(null); return; }
    const t = window.setTimeout(() => {
      api.get<RoutePreview>(`/workflows/route?text=${encodeURIComponent(goal)}`).then(setPreview).catch(() => undefined);
    }, 250);
    return () => window.clearTimeout(t);
  }, [goal]);

  // Keep launched commands' status fresh while any is still running.
  useEffect(() => {
    const running = launched.some((w) => !["COMPLETED", "BLOCKED", "FAILED", "AWAITING_APPROVAL", "ESCALATED"].includes(w.state));
    if (!running) return;
    const t = window.setTimeout(async () => {
      const fresh = await Promise.all(launched.map((w) => api.get<WorkflowSummary>(`/workflows/${w.id}`).catch(() => w)));
      setLaunched(fresh);
      onLaunched();
    }, 1200);
    return () => window.clearTimeout(t);
  }, [launched, onLaunched]);

  async function submit(text: string, commandKey?: string) {
    const needsCampaign = (commandKey ? commands.data?.find((c) => c.key === commandKey) : preview?.command)?.needs_campaign;
    const wf = await action.run("goal", () => api.post<WorkflowSummary>("/workflows/goal", {
      goal: text, command: commandKey, campaign_id: needsCampaign ? selected || null : null,
    }));
    if (wf) {
      setLaunched((prev) => [wf, ...prev].slice(0, 6));
      // Only clear the box if it still holds what was submitted (don't wipe something typed meanwhile).
      setGoal((current) => (current === text ? "" : current));
      onLaunched();
    }
  }

  const suggestions = (commands.data ?? []).flatMap((c) => c.examples.slice(0, 1).map((e) => ({ text: e, key: c.key, label: c.label })));
  const willRun = preview?.command;
  return (
    <section className="card goal-launcher">
      <div className="goal-label">
        <span className="eyebrow">Orchestrator</span>
        <b>Tell GrowthOS what to do</b>
        <span className="muted small">Type a command or pick a suggestion. The Orchestrator maps it to a known workflow (no guessing), runs the agents, and brings you only the decisions that need a human. You can run several commands at once.</span>
      </div>
      <form className="goal-row" onSubmit={(e) => { e.preventDefault(); void submit(goal); }}>
        <input value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="e.g. Follow up with leads who haven't replied" required />
        {willRun?.needs_campaign && (
          <select value={selected} onChange={(e) => setCampaignId(e.target.value)} required>
            {campaigns.length === 0 && <option value="">Create a campaign first</option>}
            {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.leads} prospects)</option>)}
          </select>
        )}
        <button className="primary" disabled={!!action.busy || !willRun || (willRun.needs_campaign && !selected)}>▶ Run</button>
      </form>
      {goal.trim().length >= 3 && preview && (
        willRun ? (
          <p className="route-preview small">→ Will run <b>{willRun.label}</b>: {willRun.description} <span className="muted">(matched: {preview.matched.join(", ")})</span></p>
        ) : (
          <p className="route-preview small unknown">I can't map that to a safe workflow yet. Try one of the suggestions below.</p>
        )
      )}
      <div className="suggestions">
        {suggestions.map((s) => (
          <button key={s.key} type="button" className="chip" title={s.label} disabled={!!action.busy}
                  onClick={() => (commands.data?.find((c) => c.key === s.key)?.needs_campaign && !selected) ? setGoal(s.text) : void submit(s.text, s.key)}>
            {s.text}
          </button>
        ))}
      </div>
      <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
      {launched.length > 0 && (
        <ul className="list launched">
          {launched.map((w) => (
            <li key={w.id}>
              <span><b>{w.goal}</b> <span className="muted small">· {commands.data?.find((c) => c.key === w.command)?.label ?? w.command}</span></span>
              <span className="actions">
                {Number(w.summary?.awaiting_approval ?? 0) > 0 && (
                  <Link to={`/workflows/${w.id}`}><b>{String(w.summary.awaiting_approval)} email(s) ready to send →</b></Link>
                )}
                <Badge value={w.state === "AWAITING_APPROVAL" ? "WAITING" : w.state} /><Link to={`/workflows/${w.id}`}>Trace →</Link></span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Terminal-style summary built only from /system/status and the recorded trace (no invented states). */
function Spotlight({ status, trace, pending }: { status: SystemStatus | null; trace: TraceEvent[]; pending: number | null }) {
  if (!status) return null;
  const latest = trace.slice(0, 3);
  const tone = (st: string) => (["FAILED", "BLOCKED"].includes(st) ? "bad" : ["WAITING", "ESCALATED"].includes(st) ? "warn" : "ok");
  return (
    <section className="spotlight" aria-label="Orchestrator workflow spotlight">
      <div className="spotlight-head"><b>● Orchestrator workflow spotlight</b><span>Central pipeline trace · from recorded events</span></div>
      <div className="spotlight-line"><span className="tag">[ORCHESTRATOR]</span>
        STATE: {status.workflows_running ? "ACTIVE" : "IDLE"} | RUNNING: {status.workflows_running} | AWAITING HUMAN: {pending ?? status.pending_approvals}
        {status.jobs_waiting_for_worker > 0 && <span className="warn"> | {status.jobs_waiting_for_worker} JOB(S) WAITING FOR THE WORKER</span>}
      </div>
      <div className="spotlight-line"><span className="tag">[POLICY_GATE]</span>
        ENFORCED ON EVERY SEND | BLOCKED (7D): <span className={status.blocked_by_policy_7d ? "warn" : "ok"}>{status.blocked_by_policy_7d}</span>
      </div>
      <div className="spotlight-line"><span className="tag">[SHARED_MEMORY]</span>
        {status.memory_entries} ENTRIES | AGENTS ACTIVE (10 MIN): {status.agents_active_10m.length ? status.agents_active_10m.map((a) => (TRACE_AGENTS[a]?.label ?? a).toUpperCase()).join(", ") : "NONE"}
      </div>
      {latest.length === 0 && <div className="spotlight-line live"><span className="tag">[LIVE_TRACE]</span>NO AGENT ACTIVITY RECORDED YET</div>}
      {latest.map((e) => (
        <div key={e.id} className="spotlight-line live"><span className="tag">[LIVE_TRACE]</span>
          {(TRACE_AGENTS[e.agent]?.label ?? e.agent).toUpperCase()} :: {e.action} → <span className={tone(e.status)}>{e.result || e.status}</span>
          <span className="tag"> · {timeAgo(e.completed_at ?? e.started_at)}</span>
        </div>
      ))}
    </section>
  );
}
