import { useState } from "react";
import { api } from "../api";
import { ApprovalCard } from "../components/trace";
import { Empty, ErrorBanner } from "../components/ui";
import { useAsync } from "../components/useAsync";
import type { ApprovalItem } from "../types";

// Tabs are filters over real approval tiers (set by the backend's escalation rules), never guessed in the UI.
const TABS: { key: string; label: string; match: (a: ApprovalItem) => boolean }[] = [
  { key: "ALL", label: "All decisions", match: () => true },
  { key: "GREEN", label: "Green — routine", match: (a) => a.tier === "GREEN" },
  { key: "YELLOW", label: "Yellow — opportunity", match: (a) => a.tier === "YELLOW" },
  { key: "RED", label: "Red — escalated", match: (a) => a.tier === "RED" },
  { key: "SOCIAL", label: "Social posts", match: (a) => a.type === "SOCIAL_POST" },
];

export default function Approvals() {
  const [status, setStatus] = useState("PENDING");
  const [tab, setTab] = useState("ALL");
  const items = useAsync(() => api.get<ApprovalItem[]>(`/approvals?status=${status}`), [status]);
  const all = items.data ?? [];
  const current = TABS.find((t) => t.key === tab) ?? TABS[0];
  const shown = all.filter(current.match);
  return (
    <>
      <div className="approval-toolbar">
        <div>
          <h1>Human Approval Center</h1>
          <p className="muted page-sub">GrowthOS escalates only what matters. Every card explains <b>why</b> it was escalated; your decision is executed through deterministic safety rules.</p>
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status filter">
          <option value="PENDING">Pending actions</option>
          <option value="APPROVED">Approved</option>
          <option value="REJECTED">Rejected</option>
          <option value="TAKEN_OVER">Taken over</option>
          <option value="AUTOMATED">Automated</option>
          <option value="CANCELLED">Cancelled</option>
        </select>
      </div>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
            {t.label} ({all.filter(t.match).length})
          </button>
        ))}
      </div>
      <ErrorBanner error={items.error} />
      {items.data && shown.length === 0 && (
        <div className="card"><Empty>{status === "PENDING" ? "Nothing waiting for you here. Routine work is being handled automatically." : "No items."}</Empty></div>
      )}
      <div className="approval-grid">
        {shown.map((a) => <ApprovalCard key={a.id} item={a} onDone={items.reload} />)}
      </div>
    </>
  );
}
