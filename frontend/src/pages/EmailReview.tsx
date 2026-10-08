import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBanner, Notice, when } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { Email, EmailReview as Review } from "../types";

const EDITABLE = ["DRAFT", "APPROVED", "FAILED"];

export default function EmailReview() {
  const { id } = useParams();
  const [filter, setFilter] = useState("DRAFT");
  const queue = useAsync(() => api.get<Email[]>(`/emails${filter ? `?status=${filter}` : ""}`), [filter]);
  const navigate = useNavigate();

  return (
    <>
      <h1>Email Review</h1>
      <div className="review-layout">
        <Card title="Queue" actions={
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="DRAFT">Drafts</option>
            <option value="APPROVED">Approved</option>
            <option value="SCHEDULED">Scheduled</option>
            <option value="SENT">Sent</option>
            <option value="FAILED">Failed</option>
            <option value="">All</option>
          </select>
        }>
          <ErrorBanner error={queue.error} />
          {queue.data?.length === 0 && <Empty>Nothing here.</Empty>}
          <ul className="list selectable">
            {queue.data?.map((e) => (
              <li key={e.id} className={e.id === id ? "selected" : ""} onClick={() => navigate(`/emails/${e.id}`)}>
                <div>
                  <div>{e.subject}</div>
                  <div className="muted small">{e.sequence_number === 0 ? "Initial" : `Follow-up ${e.sequence_number}`} · {when(e.updated_at)}</div>
                </div>
                <Badge value={e.status} />
              </li>
            ))}
          </ul>
        </Card>
        {id ? <Editor key={id} id={id} onChanged={queue.reload} /> : <Card><Empty>Select an email to review.</Empty></Card>}
      </div>
    </>
  );
}

function Editor({ id, onChanged }: { id: string; onChanged: () => void }) {
  const email = useAsync(() => api.get<Review>(`/emails/${id}`), [id]);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const action = useAction();
  const e = email.data;

  useEffect(() => {
    if (e) {
      setSubject(e.subject);
      setBody(e.body);
    }
  }, [e]);

  if (email.error) return <ErrorBanner error={email.error} />;
  if (!e) return <Card><p className="muted">Loading…</p></Card>;
  const dirty = subject !== e.subject || body !== e.body;
  const editable = EDITABLE.includes(e.status);

  async function save() {
    await action.run("save", () => api.put(`/emails/${id}`, { subject, body }), "Saved. Edited emails need approval again.");
    await email.reload();
    onChanged();
  }
  async function approve() {
    if (dirty) await api.put(`/emails/${id}`, { subject, body });
    await action.run("approve", () => api.post(`/emails/${id}/approve`), "Approved.");
    await email.reload();
    onChanged();
  }
  async function send() {
    if (!window.confirm(`Send this email to ${e!.contact_email}?`)) return;
    await action.run("send", () => api.post(`/emails/${id}/send`), "Sent.");
    await email.reload();
    onChanged();
  }

  return (
    <div className="stack">
      <Card title={`${e.company_name} · ${e.sequence_number === 0 ? "Initial email" : `Follow-up ${e.sequence_number}`}`}
            actions={<><Badge value={e.status} /><Link to={`/leads/${e.lead_id}`}>Lead →</Link></>}>
        <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
        <Notice message={action.notice} />
        <p className="muted small">To: {e.contact_name ?? "—"} &lt;{e.contact_email ?? "erased"}&gt;
          {e.draft_confidence !== null && <> · agent confidence {e.draft_confidence.toFixed(2)}</>}
          {e.edited_by_human && <> · edited by you</>}</p>
        <label>Subject<input value={subject} disabled={!editable} onChange={(ev) => setSubject(ev.target.value)} /></label>
        <label>Body<textarea rows={14} value={body} disabled={!editable} onChange={(ev) => setBody(ev.target.value)} /></label>
        <p className="muted small">An unsubscribe link is added automatically when the email is sent.</p>
        {e.last_error && <p className="muted small">Last error: {e.last_error}</p>}
        <div className="actions">
          {editable && <button disabled={!dirty || !!action.busy} onClick={save}>Save edits</button>}
          {editable && e.status !== "APPROVED" && <button className="primary" disabled={!!action.busy} onClick={approve}>Approve</button>}
          {["APPROVED", "FAILED"].includes(e.status) && (
            <button className="primary" disabled={!!action.busy || dirty || !e.send_check.allowed} onClick={send}>Send</button>
          )}
        </div>
        <div className={`send-check ${e.send_check.allowed ? "ok" : "blocked"}`}>
          <b>Safety check:</b>{" "}
          {e.send_check.allowed ? "all rules pass — ready to send." : e.send_check.reasons.map((r) => r.replace(/_/g, " ")).join(", ")}
        </div>
      </Card>
      <Card title="Research used">
        {e.personalization_used.length > 0 ? (
          <>
            <h3>Personalization in this draft</h3>
            <ul>{e.personalization_used.map((p) => <li key={p}>{p}</li>)}</ul>
          </>
        ) : <p className="muted small">This draft uses no lead-specific personalization.</p>}
        {e.research ? (
          <>
            <p>{e.research.company_summary}</p>
            <h3>Sources</h3>
            <ul className="small">
              {e.research.sources.map((s, i) => <li key={i}>{s.claim} — <span className="muted">{s.url}</span></li>)}
            </ul>
          </>
        ) : <Empty>No research available.</Empty>}
      </Card>
    </div>
  );
}
