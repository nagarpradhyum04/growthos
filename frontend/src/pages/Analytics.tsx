import { useState } from "react";
import { api } from "../api";
import { Card, Empty, ErrorBanner, Stat, pct } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { Analytics as Data, Insights } from "../types";

export default function Analytics() {
  const data = useAsync(() => api.get<Data>("/analytics"));
  const [insights, setInsights] = useState<Insights | null>(null);
  const action = useAction();
  const m = data.data?.overall;

  async function generate() {
    const res = await action.run("insights", () => api.post<{ insights: Insights }>("/analytics/insights"));
    if (res) setInsights(res.insights);
  }

  return (
    <>
      <h1>Analytics</h1>
      <ErrorBanner error={data.error ?? action.error} />
      {m && (
        <div className="stats">
          <Stat label="Leads" value={m.leads_total} />
          <Stat label="Qualified" value={m.leads_qualified} hint={`${m.leads_disqualified} disqualified`} />
          <Stat label="Emails sent" value={m.emails_sent} hint={`${m.initial_emails_sent} initial · ${m.followups_sent} follow-ups`} />
          <Stat label="Replies" value={m.replies} />
          <Stat label="Reply rate" value={pct(m.reply_rate_pct)} hint="contacts who replied / contacts emailed" />
          <Stat label="Interested" value={m.interested_contacts} hint={`conversion ${pct(m.conversion_rate_pct)}`} />
          <Stat label="Suppressed" value={m.contacts_suppressed} hint="unsubscribed or forgotten" />
          <Stat label="Opens" value="—" hint="not tracked" />
        </div>
      )}
      <Card title="Campaign performance">
        {data.data?.campaigns.length === 0 && <Empty>No campaigns yet.</Empty>}
        {!!data.data?.campaigns.length && (
          <table>
            <thead><tr><th>Campaign</th><th>Leads</th><th>Qualified</th><th>Sent</th><th>Follow-ups</th><th>Replies</th><th>Reply rate</th><th>Interested</th></tr></thead>
            <tbody>
              {data.data.campaigns.map((c) => (
                <tr key={c.campaign_id}>
                  <td>{c.name}</td><td>{c.leads_total}</td><td>{c.leads_qualified}</td><td>{c.emails_sent}</td>
                  <td>{c.followups_sent}</td><td>{c.replies}</td><td>{pct(c.reply_rate_pct)}</td><td>{c.interested_contacts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {m && Object.keys(m.reply_breakdown).length > 0 && (
          <p className="small">Reply types: {Object.entries(m.reply_breakdown).map(([k, v]) => `${k.replace(/_/g, " ").toLowerCase()} ${v}`).join(" · ")}</p>
        )}
      </Card>
      <Card title="AI insights" actions={<button className="primary" disabled={!!action.busy} onClick={generate}>{action.busy ? "Analyzing…" : "Generate insights"}</button>}>
        {!insights && <Empty>The Analytics Agent explains these numbers. It is only allowed to use the metrics above.</Empty>}
        {insights && (
          <>
            <p>{insights.summary}</p>
            <div className="grid-3">
              <div><h3>What worked</h3><ul>{insights.what_worked.map((x) => <li key={x}>{x}</li>)}</ul></div>
              <div><h3>What didn't</h3><ul>{insights.what_did_not_work.map((x) => <li key={x}>{x}</li>)}</ul></div>
              <div><h3>Recommendations</h3><ul>{insights.recommendations.map((x) => <li key={x}>{x}</li>)}</ul></div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
