import { type FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { Card, ErrorBanner, Notice } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { Me } from "../types";

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
