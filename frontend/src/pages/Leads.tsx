import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBanner, when } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { Campaign, LeadDetail, LeadListItem } from "../types";

const EMPTY = { campaign_id: "", company_name: "", website: "", notes: "", contact_name: "", contact_role: "", contact_email: "" };

export default function Leads() {
  const [campaignFilter, setCampaignFilter] = useState("");
  const leads = useAsync(
    () => api.get<LeadListItem[]>(`/leads${campaignFilter ? `?campaign_id=${campaignFilter}` : ""}`),
    [campaignFilter],
  );
  const campaigns = useAsync(() => api.get<Campaign[]>("/campaigns"));
  const [form, setForm] = useState(EMPTY);
  const [showForm, setShowForm] = useState(false);
  const [showBulk, setShowBulk] = useState(false);
  const [bulk, setBulk] = useState("");
  const [bulkResult, setBulkResult] = useState<string | null>(null);

  async function importBulk(e: FormEvent) {
    e.preventDefault();
    const prospects = bulk.split("\n").map((l) => l.split("|").map((x) => x.trim())).filter((r) => r[0])
      .map(([company_name, contact_email, contact_name = "", contact_role = "", notes = "", website = ""]) =>
        ({ company_name, contact_email, contact_name, contact_role, notes, website }));
    const campaign_id = form.campaign_id || campaigns.data?.[0]?.id || "";
    const res = await action.run("import", () => api.post<{ created: number; results: { company_name: string; status: string; reason?: string }[] }>("/leads/bulk", { campaign_id, prospects }));
    if (res) {
      const skipped = res.results.filter((r) => r.status === "skipped");
      setBulkResult(`${res.created} imported${skipped.length ? `; skipped: ${skipped.map((r) => `${r.company_name} (${r.reason})`).join(", ")}` : ""}`);
      leads.reload();
    }
  }
  const action = useAction();
  const navigate = useNavigate();

  async function create(e: FormEvent) {
    e.preventDefault();
    const campaign_id = form.campaign_id || campaigns.data?.[0]?.id || "";
    const lead = await action.run("create", () => api.post<LeadDetail>("/leads", { ...form, campaign_id }));
    if (lead) navigate(`/leads/${lead.id}`);
  }

  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  return (
    <>
      <div className="page-header">
        <h1>Leads</h1>
        <div className="actions">
          <select value={campaignFilter} onChange={(e) => setCampaignFilter(e.target.value)}>
            <option value="">All campaigns</option>
            {campaigns.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button onClick={() => setShowBulk(!showBulk)}>{showBulk ? "Close import" : "Import prospects"}</button>
          <button className="primary" onClick={() => setShowForm(!showForm)}>{showForm ? "Close" : "Add lead"}</button>
        </div>
      </div>
      <ErrorBanner error={leads.error ?? action.error} onClose={() => action.setError(null)} />

      {showBulk && (
        <Card title="Import prospects">
          <p className="small muted">One prospect per line: <code>Company | email | contact name | role | notes (evidence) | website</code>. Opted-out and duplicate contacts are skipped by the backend.</p>
          <form className="stack" onSubmit={importBulk}>
            <select value={form.campaign_id} onChange={set("campaign_id")}>
              {campaigns.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <textarea rows={5} value={bulk} onChange={(e) => setBulk(e.target.value)} placeholder="Northgate Physio | morgan@northgate.example | Morgan Blake | Ops Director | Runs 6 clinics with 140 employees" />
            <button className="primary" disabled={!!action.busy}>Import</button>
          </form>
          {bulkResult && <p className="small">{bulkResult}</p>}
        </Card>
      )}

      {showForm && (
        <Card title="New lead">
          {campaigns.data?.length === 0 ? (
            <Empty>Create a <Link to="/campaigns">campaign</Link> first.</Empty>
          ) : (
            <form className="form-grid" onSubmit={create}>
              <label>Campaign
                <select value={form.campaign_id} onChange={set("campaign_id")}>
                  {campaigns.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </label>
              <label>Company name<input required value={form.company_name} onChange={set("company_name")} /></label>
              <label>Website<input placeholder="https://example.com" value={form.website} onChange={set("website")} /></label>
              <label>Contact name<input value={form.contact_name} onChange={set("contact_name")} /></label>
              <label>Contact role<input value={form.contact_role} onChange={set("contact_role")} /></label>
              <label>Contact email<input type="email" required value={form.contact_email} onChange={set("contact_email")} /></label>
              <label className="span-2">Notes (optional, used as a cited source)
                <textarea rows={2} value={form.notes} onChange={set("notes")} />
              </label>
              <div className="span-2"><button className="primary" disabled={!!action.busy}>Create lead</button></div>
            </form>
          )}
        </Card>
      )}

      <Card>
        {leads.data?.length === 0 && <Empty>No leads yet.</Empty>}
        {!!leads.data?.length && (
          <table>
            <thead>
              <tr><th>Company</th><th>Contact</th><th>Score</th><th>Status</th><th>Campaign</th><th>Last activity</th></tr>
            </thead>
            <tbody>
              {leads.data.map((l) => (
                <tr key={l.id} className="clickable" onClick={() => navigate(`/leads/${l.id}`)}>
                  <td><Link to={`/leads/${l.id}`}>{l.company_name}</Link>{l.disabled && <span className="muted small"> (disabled)</span>}</td>
                  <td>{l.contact_name ?? <span className="muted">—</span>}<div className="muted small">{l.contact_email ?? "erased"}</div></td>
                  <td>{l.qualification_score ?? "—"}</td>
                  <td><Badge value={l.status} /></td>
                  <td>{l.campaign_name}</td>
                  <td className="muted small">{when(l.last_activity_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
