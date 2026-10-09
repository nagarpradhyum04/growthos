import { type FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { Card, ErrorBanner, Notice } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { Me, Policy } from "../types";
import { BusinessIdBanner } from "./Customers";

interface Profile {
  company_name: string;
  company_description: string;
  products_services: string;
  target_customers: string;
  value_proposition: string;
  industries: string[];
  target_company_sizes: string[];
  tone: string;
  website: string;
  key_differentiators: string;
  campaign_goals: string;
  sender_name: string;
}

const TEXT_FIELDS: [keyof Profile, string, boolean][] = [
  ["company_name", "Company name", false],
  ["website", "Website", false],
  ["sender_name", "Sender name (email sign-off)", false],
  ["tone", "Tone of voice", false],
  ["company_description", "Company description", true],
  ["products_services", "Products / services", true],
  ["value_proposition", "Value proposition", true],
  ["target_customers", "Target customers", true],
  ["key_differentiators", "Key differentiators", true],
  ["campaign_goals", "Campaign goals", true],
];

export default function Settings() {
  const profile = useAsync(() => api.get<Profile>("/business-profile"));
  const me = useAsync(() => api.get<Me>("/auth/me"));
  const [form, setForm] = useState<Profile | null>(null);
  const [lists, setLists] = useState({ industries: "", target_company_sizes: "" });
  const action = useAction();

  useEffect(() => {
    if (profile.data) {
      setForm(profile.data);
      setLists({ industries: profile.data.industries.join(", "), target_company_sizes: profile.data.target_company_sizes.join(", ") });
    }
  }, [profile.data]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
    await action.run("save", () => api.put("/business-profile", {
      ...form, industries: split(lists.industries), target_company_sizes: split(lists.target_company_sizes),
    }), "Business profile saved. Agents use it for qualification and writing.");
  }

  async function toggleAutomation(enabled: boolean) {
    await action.run("settings", () => api.patch("/organization/settings", { automated_sending_enabled: enabled }));
    me.reload();
  }

  if (!form) return <ErrorBanner error={profile.error} />;
  return (
    <>
      <h1>Business Profile</h1>
      <p className="muted">This is the knowledge your agents work from. Nothing here is "remembered" by the AI — it is read from your database for every task.</p>
      <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
      <Notice message={action.notice} />
      <Card>
        <form className="form-grid" onSubmit={save}>
          {TEXT_FIELDS.map(([key, label, long]) => (
            <label key={key} className={long ? "span-2" : ""}>
              {label}
              {long ? (
                <textarea rows={2} value={form[key] as string} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
              ) : (
                <input value={form[key] as string} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
              )}
            </label>
          ))}
          <label>Target industries (comma separated)
            <input placeholder="Logistics, Software" value={lists.industries} onChange={(e) => setLists({ ...lists, industries: e.target.value })} />
          </label>
          <label>Target company sizes (employee ranges)
            <input placeholder="20-200, 200-1000" value={lists.target_company_sizes} onChange={(e) => setLists({ ...lists, target_company_sizes: e.target.value })} />
          </label>
          <div className="span-2"><button className="primary" disabled={!!action.busy}>Save profile</button></div>
        </form>
      </Card>
      <BusinessIdBanner />
      <PolicyCard />
      {me.data && (
        <Card title="Sending mode">
          <label className="checkbox">
            <input type="checkbox" checked={me.data.organization.automated_sending_enabled}
                   onChange={(e) => toggleAutomation(e.target.checked)} />
            Send follow-ups automatically (without manual approval)
          </label>
          <p className="muted small">Initial emails always need your approval. Even in automatic mode, every email passes the same safety
            checks: unsubscribe, Forget Me, suppression, paused campaigns, follow-up limits and duplicate prevention.</p>
        </Card>
      )}
    </>
  );
}

const RULE_LABELS: Record<string, string> = {
  purchase_intent: "Purchase intent", large_order: "Large order", pricing_inquiry: "Pricing inquiry",
  discount_request: "Discount request", meeting_request: "Meeting request", routine_question: "Routine question",
  greeting: "Greeting / thanks", brochure_request: "Brochure / info request",
};

function PolicyCard() {
  const policy = useAsync(() => api.get<Policy>("/policy"));
  const [p, setP] = useState<Policy | null>(null);
  const action = useAction();
  useEffect(() => { if (policy.data) setP(policy.data); }, [policy.data]);
  if (!p) return null;
  const set = <K extends keyof Policy>(k: K, v: Policy[K]) => setP({ ...p, [k]: v });
  async function save() {
    const { locked_categories: _locked, ...body } = p!;
    void _locked;
    if (await action.run("policy", () => api.put("/policy", body), "Rules saved. The backend enforces them on every action.")) policy.reload();
  }
  return (
    <Card title="Automation & safety rules" actions={<span className="muted small">enforced by the backend, never by the AI</span>}>
      <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
      <Notice message={action.notice} />
      <div className="form-grid">
        <label>Max messages per person / 30 days
          <input type="number" min={1} value={p.max_messages_per_contact_30d} onChange={(e) => set("max_messages_per_contact_30d", Number(e.target.value))} />
        </label>
        <label>Minimum hours between messages
          <input type="number" min={0} value={p.min_hours_between_messages} onChange={(e) => set("min_hours_between_messages", Number(e.target.value))} />
        </label>
        <label>Never contact these domains (comma separated)
          <input value={p.blocked_domains.join(", ")} onChange={(e) => set("blocked_domains", e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} />
        </label>
        <label>Banned phrases (block sending)
          <input value={p.banned_phrases.join(", ")} onChange={(e) => set("banned_phrases", e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} />
        </label>
        <label>Large order threshold (value)
          <input type="number" min={0} value={p.large_order_threshold} onChange={(e) => set("large_order_threshold", Number(e.target.value))} />
        </label>
        <label>Lifecycle messages per customer / 7 days
          <input type="number" min={0} value={p.lifecycle_max_per_7d} onChange={(e) => set("lifecycle_max_per_7d", Number(e.target.value))} />
        </label>
      </div>
      <h3>Escalation rules (incoming messages)</h3>
      <table className="compact">
        <tbody>
          {Object.entries(p.escalation_rules).map(([k, v]) => (
            <tr key={k}><td>{RULE_LABELS[k] ?? k}</td>
              <td><select value={v} onChange={(e) => set("escalation_rules", { ...p.escalation_rules, [k]: e.target.value })}>
                <option value="escalate">Escalate to me</option><option value="automate">Automate</option></select></td></tr>
          ))}
          <tr><td>{p.locked_categories.map((c) => c.replace("_", " ")).join(", ")}</td><td><span className="badge bad">Always escalated (locked)</span></td></tr>
        </tbody>
      </table>
      <div className="stack" style={{ marginTop: 10 }}>
        <label className="checkbox"><input type="checkbox" checked={p.auto_handle_routine} onChange={(e) => set("auto_handle_routine", e.target.checked)} /> Auto-handle routine customer messages (answers only from the knowledge base)</label>
        <label className="checkbox"><input type="checkbox" checked={p.lifecycle_enabled} onChange={(e) => set("lifecycle_enabled", e.target.checked)} /> Send lifecycle follow-ups (setup help, check-ins, warranty expiry, post-service)</label>
        <label className="checkbox"><input type="checkbox" checked={p.social_weekly_enabled} onChange={(e) => set("social_weekly_enabled", e.target.checked)} /> Draft one static + one video social post every week (always waits for your approval; never auto-published)</label>
        <div className="actions small">Social platforms:
          {["instagram", "facebook", "linkedin", "x", "tiktok"].map((pl) => (
            <label key={pl} className="checkbox" style={{ marginBottom: 0 }}><input type="checkbox" checked={p.social_platforms.includes(pl)}
              onChange={(e) => set("social_platforms", e.target.checked ? [...p.social_platforms, pl] : p.social_platforms.filter((x) => x !== pl))} /> {pl}</label>
          ))}
        </div>
        <label className="checkbox"><input type="checkbox" checked={p.warranty_auto_approve} onChange={(e) => set("warranty_auto_approve", e.target.checked)} /> Auto-approve warranty claims that pass the eligibility rules (off = always human)</label>
      </div>
      <button className="primary" onClick={save} disabled={!!action.busy}>Save rules</button>
    </Card>
  );
}
