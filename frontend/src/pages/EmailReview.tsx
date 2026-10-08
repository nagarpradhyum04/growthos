import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { SafetyPanel } from "../components/SafetyPanel";
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
      <p className="muted page-sub">Every AI-written email waits here. Nothing is sent until a human approves it <i>and</i> the backend safety gate passes.</p>
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
  const [editing, setEditing] = useState(false);
  const [rejected, setRejected] = useState(false);
  const action = useAction();
  const navigate = useNavigate();
  const e = email.data;

  useEffect(() => {
    if (e) {
      setSubject(e.subject);
      setBody(e.body);
    }
  }, [e]);

  if (rejected) return <Card><Notice message="Draft rejected. The lead is back to Qualified — generate a new draft from the lead page." /></Card>;
  if (email.error) return <ErrorBanner error={email.error} />;
  if (!e) return <Card><p className="muted">Loading…</p></Card>;
  const dirty = subject !== e.subject || body !== e.body;
  const editable = EDITABLE.includes(e.status);
  const sent = ["SENT", "DELIVERED", "REPLIED", "COMPLETED"].includes(e.status);
  // Problems other than "needs approval" can't be fixed by approving; the backend would refuse the send.
  const otherBlockers = e.send_check.checks.filter((c) => !c.passed && !["human_approved", "send_gate"].includes(c.key));
  const writer = e.sequence_number === 0 ? "Outreach Agent" : "Follow-up Agent";

  async function refresh() {
    await email.reload();
    onChanged();
  }
  async function save() {
    if (await action.run("save", () => api.put(`/emails/${id}`, { subject, body }), "Saved. Edited emails need approval again.")) setEditing(false);
    await refresh();
  }
  async function approveOnly() {
    await action.run("approve", async () => {
      if (dirty) await api.put(`/emails/${id}`, { subject, body });
      return api.post(`/emails/${id}/approve`);
    }, "Approved by you. The backend safety gate runs again at send time.");
    setEditing(false);
    await refresh();
  }
  async function approveAndSend() {
    if (!window.confirm(`Approve and send this email to ${e!.contact_email}?\nThe backend safety gate will check it once more before sending.`)) return;
    await action.run("send", async () => {
      if (dirty) await api.put(`/emails/${id}`, { subject, body });
      if (e!.status !== "APPROVED" || dirty) await api.post(`/emails/${id}/approve`);
      return api.post(`/emails/${id}/send`);
    }, "Approved and sent — the safety gate passed.");
    setEditing(false);
    await refresh();
  }
  async function reject() {
    if (!window.confirm("Reject this AI draft? It will not be sent. The agent's original output is kept for audit.")) return;
    if (await action.run("reject", () => api.post(`/emails/${id}/reject`))) {
      setRejected(true);
      onChanged();
      navigate("/emails", { replace: true });
    }
  }

  return (
    <div className="stack">
      <div className={`hitl-banner ${sent ? "done" : ""}`}>
        <span className="hitl-step">AI drafted<small>{writer}</small></span>
        <span className="hitl-arrow">→</span>
        <span className={`hitl-step ${e.approved_at ? "ok" : "now"}`}>Human review<small>{e.approved_at ? `approved ${when(e.approved_at)}` : "you decide"}</small></span>
        <span className="hitl-arrow">→</span>
        <span className={`hitl-step ${sent ? "ok" : e.send_check.allowed ? "ok" : otherBlockers.length ? "bad" : ""}`}>Safety gate<small>backend can_send()</small></span>
        <span className="hitl-arrow">→</span>
        <span className={`hitl-step ${sent ? "ok" : ""}`}>Send<small>{sent ? when(e.sent_at) : "only after both"}</small></span>
      </div>

      <Card title={`${e.company_name} · ${e.sequence_number === 0 ? "Initial email" : `Follow-up ${e.sequence_number}`}`}
            actions={<><Badge value={e.status} /><Link to={`/leads/${e.lead_id}`}>Lead →</Link></>}>
        <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
        <Notice message={action.notice} />
        <p className="muted small">
          To: {e.contact_name ?? "—"} &lt;{e.contact_email ?? "erased"}&gt;
          {e.draft_confidence !== null && <> · AI confidence <b>{Math.round(e.draft_confidence * 100)}%</b></>}
          {e.edited_by_human && <> · edited by a human</>}
        </p>
        {editing ? (
          <>
            <label>Subject<input value={subject} onChange={(ev) => setSubject(ev.target.value)} /></label>
            <label>Body<textarea rows={14} value={body} onChange={(ev) => setBody(ev.target.value)} /></label>
          </>
        ) : (
          <div className="email-preview">
            <div className="email-subject">{subject}</div>
            <div className="email-body">{body}</div>
          </div>
        )}
        <p className="muted small">An unsubscribe link is added automatically when the email is sent.</p>
        {e.last_error && <p className="muted small">Last error: {e.last_error}</p>}
        {editable && (
          <div className="actions review-actions">
            {editing ? (
              <>
                <button disabled={!dirty || !!action.busy} onClick={save}>Save edits</button>
                <button className="link" onClick={() => { setSubject(e.subject); setBody(e.body); setEditing(false); }}>Cancel</button>
              </>
            ) : (
              <button disabled={!!action.busy} onClick={() => setEditing(true)}>✎ Edit draft</button>
            )}
            <span className="spacer" />
            <button className="danger-outline" disabled={!!action.busy} onClick={reject}>Reject</button>
            {e.status !== "APPROVED" && <button disabled={!!action.busy} onClick={approveOnly}>Approve only</button>}
            <button className="primary" disabled={!!action.busy || otherBlockers.length > 0} onClick={approveAndSend}
                    title={otherBlockers.length ? "Blocked by backend safety rules" : ""}>
              {e.status === "APPROVED" && !dirty ? "Send" : "Approve & Send"}
            </button>
          </div>
        )}
        <SafetyPanel check={e.send_check} sent={sent} />
      </Card>

      <Card title="Evidence behind this draft">
        <h3>Personalization used</h3>
        {e.personalization_used.length > 0 ? (
          <ul className="evidence-list">
            {e.personalization_used.map((p) => {
              const src = e.research?.sources.find((s) => s.claim.toLowerCase().includes(p.toLowerCase()) || p.toLowerCase().includes(s.claim.toLowerCase()));
              return (
                <li key={p} className="used">
                  ✓ {p}{" "}
                  {src ? (src.url.startsWith("http")
                    ? <a className="source-link" href={src.url} target="_blank" rel="noreferrer">{src.url.replace(/^https?:\/\//, "")}</a>
                    : <span className="source-link muted">{src.url === "user-notes" ? "your lead notes" : src.url}</span>)
                    : <span className="muted small">(research summary)</span>}
                </li>
              );
            })}
          </ul>
        ) : <p className="muted small">No lead-specific personalization — the research did not contain verified details to use.</p>}
        {e.research ? (
          <>
            <h3>Research summary</h3>
            <p>{e.research.company_summary}</p>
            <h3>Sources</h3>
            {e.research.sources.length ? (
              <ol className="sources">
                {e.research.sources.map((s, i) => (
                  <li key={i}>“{s.claim}” {s.url.startsWith("http")
                    ? <a className="source-link" href={s.url} target="_blank" rel="noreferrer">{s.url.replace(/^https?:\/\//, "")}</a>
                    : <span className="source-link muted">{s.url === "user-notes" ? "your lead notes" : s.url}</span>}</li>
                ))}
              </ol>
            ) : <p className="unknown small">No sources.</p>}
          </>
        ) : <Empty>No research available.</Empty>}
      </Card>
    </div>
  );
}
