import { Link } from "react-router-dom";
import { api } from "../api";
import { AGENTS, fmtDuration, summarizeRun, timeAgo } from "../components/agents";
import { Badge, Card, Empty, ErrorBanner, Stat, pct } from "../components/ui";
import { useAsync } from "../components/useAsync";
import type { AgentRun, Analytics, Email, LeadListItem } from "../types";

export default function Dashboard() {
  const analytics = useAsync(() => api.get<Analytics>("/analytics"));
  const drafts = useAsync(() => api.get<Email[]>("/emails?status=DRAFT"));
  const runs = useAsync(() => api.get<AgentRun[]>("/agent-runs?limit=200"));
  const leads = useAsync(() => api.get<LeadListItem[]>("/leads?limit=500"));
  const m = analytics.data?.overall;
  const companyOf = new Map((leads.data ?? []).map((l) => [l.id, l.company_name]));

  return (
    <>
      <h1>GrowthOS Command Center</h1>
      <p className="muted page-sub">Six AI agents reason and recommend. Deterministic backend rules and human approval decide what is allowed to happen.</p>
      <ErrorBanner error={analytics.error ?? drafts.error ?? runs.error} />
      {m && (
        <div className="stats">
          <Stat label="Active campaigns" value={m.active_campaigns} />
          <Stat label="Total leads" value={m.leads_total} />
          <Stat label="Qualified leads" value={m.leads_qualified} hint={`${m.leads_disqualified} not contacted`} />
          <Stat label="Emails sent" value={m.emails_sent} />
          <Stat label="Replies" value={m.replies} />
          <Stat label="Interested leads" value={m.interested_contacts} hint={`conversion ${pct(m.conversion_rate_pct)}`} />
          <Stat label="Follow-ups pending" value={m.followups_pending} hint={`${m.followups_sent} sent`} />
          <Stat label="Reply rate" value={pct(m.reply_rate_pct)} hint={m.contacts_emailed ? `${m.contacts_replied} of ${m.contacts_emailed} contacts` : "no emails yet"} />
        </div>
      )}

      <Card title="Agent status" actions={<span className="muted small">From recorded agent runs</span>}>
        <div className="agent-grid">
          {Object.entries(AGENTS).map(([key, a]) => {
            const mine = (runs.data ?? []).filter((r) => r.agent_name === key);
            const last = mine[0];
            const state = !last ? "idle" : last.status === "RUNNING" ? "running" : last.status === "FAILED" ? "failed" : "ready";
            const ok = mine.filter((r) => r.status === "SUCCEEDED").length;
            return (
              <div key={key} className={`agent-tile as-${state}`}>
                <div className="agent-tile-head">
                  <span className="agent-avatar">{a.short}</span>
                  <div>
                    <b>{a.label}</b>
                    <div className="muted small">{a.role}</div>
                  </div>
                </div>
                <div className="agent-tile-state">
                  <span className={`pill pill-${state === "ready" ? "completed" : state === "failed" ? "blocked" : state === "running" ? "running" : "pending"}`}>
                    {state === "idle" ? "Idle — not run yet" : state === "ready" ? "Ready" : state === "running" ? "Running" : "Last run failed"}
                  </span>
                  {last && <span className="muted small">last {timeAgo(last.started_at)} · {ok}/{mine.length} runs ok</span>}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      <div className="grid-2">
        <Card title="Recent agent activity">
          {runs.data?.length === 0 && <Empty>No agent has run yet. Open a lead and click “Run full pipeline”.</Empty>}
          <ul className="activity-feed">
            {runs.data?.slice(0, 10).map((r) => (
              <li key={r.id}>
                <span className={`feed-dot st-${r.status}`} aria-hidden />
                <div>
                  <div>
                    <b>{AGENTS[r.agent_name]?.label ?? r.agent_name}</b>
                    {r.lead_id && companyOf.get(r.lead_id) && <> · <Link to={`/leads/${r.lead_id}`}>{companyOf.get(r.lead_id)}</Link></>}
                  </div>
                  <div className="small">{summarizeRun(r)}</div>
                  <div className="muted small">{timeAgo(r.started_at)}{r.latency_ms != null && ` · ${fmtDuration(r.latency_ms)}`} · {r.prompt_version}</div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <div className="stack-lg">
          <Card title="Waiting for human review" actions={<Link to="/emails">Open review queue →</Link>}>
            {drafts.data && drafts.data.length === 0 && <Empty>No drafts waiting. Generate emails from qualified leads.</Empty>}
            <ul className="list">
              {drafts.data?.slice(0, 6).map((e) => (
                <li key={e.id}>
                  <Link to={`/emails/${e.id}`}>{e.subject}</Link>
                  <span className="muted small">{e.sequence_number === 0 ? "Initial" : `Follow-up ${e.sequence_number}`}</span>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Campaigns" actions={<Link to="/campaigns">Manage →</Link>}>
            {analytics.data?.campaigns.length === 0 && <Empty>No campaigns yet.</Empty>}
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

      <Card title="How GrowthOS works">
        <ol className="flow-h">
          <li><span className="kind-chip agent">AI</span><b>Research</b><span>Public evidence, sources cited, unknowns stay unknown</span></li>
          <li><span className="kind-chip agent">AI</span><b>Qualify</b><span>Rates fit with evidence; fixed rules compute the score</span></li>
          <li><span className="kind-chip agent">AI</span><b>Draft</b><span>Personalized only with verified research</span></li>
          <li><span className="kind-chip human">Human</span><b>Review</b><span>Edit, approve or reject</span></li>
          <li><span className="kind-chip rule">Rule</span><b>Safety gate</b><span>Opt-out, suppression, pause, limits, duplicates</span></li>
          <li><span className="kind-chip agent">AI</span><b>Replies &amp; follow-ups</b><span>Any reply or opt-out stops the sequence</span></li>
        </ol>
      </Card>
    </>
  );
}
