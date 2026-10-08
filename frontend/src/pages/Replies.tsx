import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBanner, when } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { Reply } from "../types";

const CLASSES = ["INTERESTED", "ASKED_QUESTION", "REQUESTED_LATER", "NOT_INTERESTED", "UNSUBSCRIBE", "OUT_OF_OFFICE", "UNKNOWN"];

export default function Replies() {
  const [filter, setFilter] = useState("");
  const replies = useAsync(() => api.get<Reply[]>(`/replies${filter === "attention" ? "?needs_attention=true" : filter ? `?classification=${filter}` : ""}`), [filter]);
  const action = useAction();

  async function analyze(id: string) {
    await action.run("analyze", () => api.post(`/replies/${id}/analyze`));
    replies.reload();
  }

  return (
    <>
      <div className="page-header">
        <h1>Replies</h1>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All replies</option>
          <option value="attention">Needs attention</option>
          {CLASSES.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
        </select>
      </div>
      <ErrorBanner error={replies.error ?? action.error} />
      <Card>
        {replies.data?.length === 0 && <Empty>No replies yet.</Empty>}
        {replies.data?.map((r) => (
          <div key={r.id} className="reply">
            <div className="reply-head">
              <Badge value={r.classification ?? "PENDING"} />
              {r.requires_human_attention && <span className="badge warn">needs attention</span>}
              {r.opt_out_detected && <span className="badge bad">opt-out enforced</span>}
              <span className="muted small">{when(r.received_at)}</span>
              <Link to={`/leads/${r.lead_id}`}>Open lead →</Link>
            </div>
            <blockquote>{r.body}</blockquote>
            {r.summary && <p className="small">{r.summary}</p>}
            {r.recommended_action && <p className="small"><b>Next:</b> {r.recommended_action}</p>}
            {!r.analyzed_at && <button disabled={!!action.busy} onClick={() => analyze(r.id)}>Analyze now</button>}
          </div>
        ))}
      </Card>
    </>
  );
}
