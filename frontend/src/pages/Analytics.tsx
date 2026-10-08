import { useState } from "react";
import { api } from "../api";
import { Card, Empty, ErrorBanner, Stat, pct } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { Analytics as Data, Insights } from "../types";

// Reply buckets requested for the demo; "Other" lists exactly what it contains.
const REPLY_BUCKETS: { label: string; keys: string[] }[] = [
  { label: "Interested", keys: ["INTERESTED"] },
  { label: "Not interested", keys: ["NOT_INTERESTED"] },
  { label: "Question", keys: ["ASKED_QUESTION"] },
  { label: "Out of office", keys: ["OUT_OF_OFFICE"] },
  { label: "Opt out", keys: ["UNSUBSCRIBE"] },
  { label: "Other (later / unclear / not yet analyzed)", keys: ["REQUESTED_LATER", "UNKNOWN", "UNANALYZED"] },
];

function HBar({ label, value, max, note }: { label: string; value: number; max: number; note?: string }) {
  const width = max > 0 ? Math.max((value / max) * 100, value > 0 ? 1.5 : 0) : 0;
  return (
    <div className="hbar" title={`${label}: ${value}${note ? ` (${note})` : ""}`}>
      <div className="hbar-label">{label}</div>
      <div className="hbar-track"><div className="hbar-fill" style={{ width: `${width}%` }} /></div>
      <div className="hbar-value">{value}{note && <span className="muted small"> {note}</span>}</div>
    </div>
  );
}

export default function Analytics() {
  const data = useAsync(() => api.get<Data>("/analytics"));
  const [insights, setInsights] = useState<Insights | null>(null);
  const action = useAction();
  const m = data.data?.overall;

  async function generate() {
    const res = await action.run("insights", () => api.post<{ insights: Insights }>("/analytics/insights"));
    if (res) setInsights(res.insights);
  }

  const funnel = m
    ? [
        { label: "Leads", value: m.leads_total },
        { label: "Qualified", value: m.leads_qualified },
        { label: "Contacts emailed", value: m.contacts_emailed },
        { label: "Contacts replied", value: m.contacts_replied },
        { label: "Interested", value: m.interested_contacts },
      ]
    : [];
  const replyTotal = m ? Object.values(m.reply_breakdown).reduce((a, b) => a + b, 0) : 0;
  const buckets = REPLY_BUCKETS.map((b) => ({
    label: b.label,
    value: b.keys.reduce((sum, k) => sum + (m?.reply_breakdown[k] ?? 0), 0),
  }));
  const campaigns = data.data?.campaigns ?? [];
  const maxRate = Math.max(0, ...campaigns.map((c) => c.reply_rate_pct ?? 0));

  return (
    <>
      <h1>Analytics</h1>
      <p className="muted page-sub">All numbers are counted from the database. The Analytics Agent may only explain these numbers — any number it invents is rejected by the backend.</p>
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
          <Stat label="Opens" value="—" hint="not tracked (by design)" />
        </div>
      )}

      <div className="grid-2">
        <Card title="Conversion funnel">
          {!m || m.leads_total === 0 ? <Empty>No leads yet — the funnel appears once leads exist.</Empty> : (
            <div className="funnel">
              {funnel.map((f, i) => {
                const prev = i > 0 ? funnel[i - 1].value : null;
                const note = prev ? `${Math.round((f.value / prev) * 100)}% of previous` : undefined;
                return <HBar key={f.label} label={f.label} value={f.value} max={funnel[0].value} note={prev !== null ? note : undefined} />;
              })}
              {m.contacts_emailed < 10 && m.contacts_emailed > 0 && (
                <p className="muted small">Small sample ({m.contacts_emailed} contacts emailed) — treat rates as directional.</p>
              )}
            </div>
          )}
        </Card>
        <Card title="Reply classification">
          {replyTotal === 0 ? <Empty>No replies yet — nothing to classify.</Empty> : (
            <div className="funnel">
              {buckets.map((b) => <HBar key={b.label} label={b.label} value={b.value} max={Math.max(...buckets.map((x) => x.value))} />)}
              <p className="muted small">{replyTotal} replies total.</p>
            </div>
          )}
        </Card>
      </div>

      <Card title="Campaign comparison">
        {campaigns.length === 0 ? <Empty>No campaigns yet.</Empty> : (
          <table>
            <thead>
              <tr><th>Campaign</th><th className="num">Leads</th><th className="num">Qualified</th><th className="num">Emails sent</th><th className="num">Replies</th><th>Reply rate</th><th className="num">Interested conversion</th></tr>
            </thead>
            <tbody>
              {campaigns.map((c) => (
                <tr key={c.campaign_id}>
                  <td><b>{c.name}</b><div className="muted small">{c.status.toLowerCase()}</div></td>
                  <td className="num">{c.leads_total}</td>
                  <td className="num">{c.leads_qualified}</td>
                  <td className="num">{c.emails_sent}</td>
                  <td className="num">{c.replies}</td>
                  <td className="rate-cell">
                    {c.reply_rate_pct === null ? <span className="muted">no emails</span> : (
                      <div className="inline-bar" title={`${c.reply_rate_pct}%`}>
                        <div className="hbar-track"><div className="hbar-fill" style={{ width: `${maxRate ? (c.reply_rate_pct / maxRate) * 100 : 0}%` }} /></div>
                        <span>{c.reply_rate_pct}%</span>
                      </div>
                    )}
                  </td>
                  <td className="num">{pct(c.conversion_rate_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Analytics Agent insights" actions={<button className="primary" disabled={!!action.busy} onClick={generate}>{action.busy ? "Analyzing…" : "Generate insights"}</button>}>
        {!insights && <Empty>The Analytics Agent explains the metrics above. Numbers that do not appear in the data are rejected.</Empty>}
        {insights && (
          <>
            <p>{insights.summary}</p>
            <div className="grid-3">
              <div><h3>What worked</h3>{insights.what_worked.length ? <ul>{insights.what_worked.map((x) => <li key={x}>{x}</li>)}</ul> : <p className="muted small">Nothing conclusive yet.</p>}</div>
              <div><h3>What didn't</h3>{insights.what_did_not_work.length ? <ul>{insights.what_did_not_work.map((x) => <li key={x}>{x}</li>)}</ul> : <p className="muted small">Nothing conclusive yet.</p>}</div>
              <div><h3>Recommendations</h3><ul>{insights.recommendations.map((x) => <li key={x}>{x}</li>)}</ul></div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
