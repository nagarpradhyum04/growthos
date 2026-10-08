import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBanner, Stat, pct } from "../components/ui";
import { useAsync } from "../components/useAsync";
import type { Analytics, Email } from "../types";

export default function Dashboard() {
  const analytics = useAsync(() => api.get<Analytics>("/analytics"));
  const drafts = useAsync(() => api.get<Email[]>("/emails?status=DRAFT"));
  const m = analytics.data?.overall;

  return (
    <>
      <h1>Dashboard</h1>
      <ErrorBanner error={analytics.error ?? drafts.error} />
      {m && (
        <div className="stats">
          <Stat label="Active campaigns" value={m.active_campaigns} />
          <Stat label="Total leads" value={m.leads_total} />
          <Stat label="Qualified leads" value={m.leads_qualified} />
          <Stat label="Emails sent" value={m.emails_sent} />
          <Stat label="Replies" value={m.replies} />
          <Stat label="Follow-ups sent" value={m.followups_sent} hint={`${m.followups_pending} pending`} />
          <Stat label="Reply rate" value={pct(m.reply_rate_pct)} />
          <Stat label="Interested" value={m.interested_contacts} hint={`conversion ${pct(m.conversion_rate_pct)}`} />
        </div>
      )}
      <div className="grid-2">
        <Card title="Drafts awaiting your review" actions={<Link to="/emails">Open review queue →</Link>}>
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
      <Card title="How GrowthOS works">
        <ol className="flow">
          <li><b>Research</b> — public website evidence, sources cited, unknowns stay unknown.</li>
          <li><b>Qualify</b> — the agent rates fit with evidence; the score is computed by fixed rules.</li>
          <li><b>Draft</b> — a personalized email built only from verified research.</li>
          <li><b>You review</b> — edit, approve, send. Every send passes the safety check.</li>
          <li><b>Follow up</b> — automatic drafts when there is no reply, stopped by any reply or opt-out.</li>
        </ol>
      </Card>
    </>
  );
}
