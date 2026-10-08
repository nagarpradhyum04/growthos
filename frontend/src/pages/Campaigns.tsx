import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBanner } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { Campaign } from "../types";

const EMPTY = { name: "", objective: "", target_audience: "", max_followups: "", followup_delay_days: "" };

export default function Campaigns() {
  const campaigns = useAsync(() => api.get<Campaign[]>("/campaigns"));
  const [form, setForm] = useState(EMPTY);
  const action = useAction();

  async function create(e: FormEvent) {
    e.preventDefault();
    const body = {
      name: form.name,
      objective: form.objective,
      target_audience: form.target_audience,
      max_followups: form.max_followups === "" ? null : Number(form.max_followups),
      followup_delay_days: form.followup_delay_days === "" ? null : Number(form.followup_delay_days),
    };
    if (await action.run("create", () => api.post("/campaigns", body), "Campaign created.")) {
      setForm(EMPTY);
      campaigns.reload();
    }
  }

  async function toggle(c: Campaign) {
    const verb = c.status === "ACTIVE" ? "pause" : "resume";
    await action.run(verb, () => api.post(`/campaigns/${c.id}/${verb}`));
    campaigns.reload();
  }

  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  return (
    <>
      <h1>Campaigns</h1>
      <ErrorBanner error={campaigns.error ?? action.error} onClose={() => action.setError(null)} />
      <Card>
        {campaigns.data?.length === 0 && <Empty>No campaigns yet — create one below.</Empty>}
        {!!campaigns.data?.length && (
          <table>
            <thead>
              <tr><th>Campaign</th><th>Target audience</th><th>Leads</th><th>Qualified</th><th>Sent</th><th>Replies</th><th>Follow-ups</th><th>Status</th><th /></tr>
            </thead>
            <tbody>
              {campaigns.data.map((c) => (
                <tr key={c.id}>
                  <td><b>{c.name}</b><div className="muted small">{c.objective}</div></td>
                  <td className="small">{c.target_audience || "—"}</td>
                  <td><Link to="/leads">{c.leads}</Link></td>
                  <td>{c.qualified_leads}</td>
                  <td>{c.emails_sent}</td>
                  <td>{c.replies}</td>
                  <td className="small">max {c.effective_max_followups}{c.followup_delay_days !== null && `, every ${c.followup_delay_days}d`}</td>
                  <td><Badge value={c.status} /></td>
                  <td>
                    {c.status !== "COMPLETED" && (
                      <button disabled={!!action.busy} onClick={() => toggle(c)}>{c.status === "ACTIVE" ? "Pause" : "Resume"}</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted small">Pausing a campaign blocks all sends and holds its follow-ups until you resume.</p>
      </Card>

      <Card title="New campaign">
        <form className="form-grid" onSubmit={create}>
          <label>Name<input required value={form.name} onChange={set("name")} /></label>
          <label>Objective<input placeholder="Book discovery calls" value={form.objective} onChange={set("objective")} /></label>
          <label className="span-2">Target audience
            <input placeholder="Sales leaders at 50-500 person logistics software companies" value={form.target_audience} onChange={set("target_audience")} />
          </label>
          <label>Max follow-ups (blank = default)<input type="number" min={0} max={10} value={form.max_followups} onChange={set("max_followups")} /></label>
          <label>Days between follow-ups (blank = default)<input type="number" min={0} max={60} value={form.followup_delay_days} onChange={set("followup_delay_days")} /></label>
          <div className="span-2"><button className="primary" disabled={!!action.busy}>Create campaign</button></div>
        </form>
      </Card>
    </>
  );
}
