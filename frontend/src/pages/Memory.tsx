import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, ErrorBanner, when } from "../components/ui";
import { useAsync } from "../components/useAsync";
import type { MemoryItem } from "../types";

const SCOPES = ["", "business", "lead", "customer", "campaign"];

export default function Memory() {
  const [scope, setScope] = useState("");
  const [category, setCategory] = useState("");
  const items = useAsync(() => api.get<MemoryItem[]>(`/memory?limit=300${scope ? `&scope=${scope}` : ""}${category ? `&category=${category}` : ""}`), [scope, category]);
  const insights = useAsync(() => api.get<MemoryItem[]>("/memory?scope=business&category=insight"));
  return (
    <>
      <h1>Shared Memory</h1>
      <p className="muted page-sub">What agents have learned and passed to each other. Research writes facts, Email Intelligence records intent, Analytics stores insights the Outreach Agent reads on its next run. Stored in Postgres; deleted with Forget Me.</p>
      <Card title="Learned insights (used by future workflows)" actions={<Link to="/analytics">Generate from Analytics →</Link>}>
        {insights.data?.length === 0 && <Empty>No insights yet — run “Generate insights” on the Analytics page after some emails are sent.</Empty>}
        <ul className="memory-list">
          {insights.data?.map((m) => <li key={m.id}><span className="mem-cat cat-insight">insight</span> {m.content}<div className="muted small">by {m.source} · {when(m.updated_at)}</div></li>)}
        </ul>
      </Card>
      <Card title="All memory" actions={
        <div className="actions">
          <select value={scope} onChange={(e) => setScope(e.target.value)}>{SCOPES.map((s) => <option key={s} value={s}>{s || "All scopes"}</option>)}</select>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {["", "research", "result", "conversation", "customer_info", "product", "preference", "insight"].map((c) => <option key={c} value={c}>{c || "All categories"}</option>)}
          </select>
        </div>}>
        <ErrorBanner error={items.error} />
        {items.data?.length === 0 && <Empty>Nothing stored yet.</Empty>}
        <table>
          <thead><tr><th>Scope</th><th>Category</th><th>Content</th><th>Written by</th><th>Updated</th></tr></thead>
          <tbody>
            {items.data?.map((m) => (
              <tr key={m.id}>
                <td className="small">{m.scope === "lead" && m.subject_id ? <Link to={`/leads/${m.subject_id}`}>lead</Link> : m.scope === "customer" && m.subject_id ? <Link to={`/customers/${m.subject_id}`}>customer</Link> : m.scope}</td>
                <td><span className={`mem-cat cat-${m.category}`}>{m.category}</span></td>
                <td className="small">{m.content}</td>
                <td className="small">{m.source}</td>
                <td className="small muted">{when(m.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
