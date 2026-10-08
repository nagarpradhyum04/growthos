import { useState } from "react";
import { api } from "../api";
import { ApprovalCard } from "../components/trace";
import { Empty, ErrorBanner } from "../components/ui";
import { useAsync } from "../components/useAsync";
import type { ApprovalItem } from "../types";

export default function Approvals() {
  const [status, setStatus] = useState("PENDING");
  const items = useAsync(() => api.get<ApprovalItem[]>(`/approvals?status=${status}`), [status]);
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Pending human actions</h1>
          <p className="muted page-sub">GrowthOS escalates only what matters. Every card says <b>why</b> it was escalated; your decision runs through the same safety rules.</p>
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="PENDING">Pending</option>
          <option value="APPROVED">Approved</option>
          <option value="REJECTED">Rejected</option>
          <option value="TAKEN_OVER">Taken over</option>
          <option value="AUTOMATED">Automated</option>
          <option value="CANCELLED">Cancelled</option>
        </select>
      </div>
      <ErrorBanner error={items.error} />
      {items.data?.length === 0 && <div className="card"><Empty>Nothing waiting for you. Routine work is being handled automatically.</Empty></div>}
      <div className="approval-grid">
        {items.data?.map((a) => <ApprovalCard key={a.id} item={a} onDone={items.reload} />)}
      </div>
    </>
  );
}
