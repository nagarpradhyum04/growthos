import { type FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBanner, Notice, when } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import type { Contact, Job, LeadDetail as Lead } from "../types";

type Criterion = { rating: string; weight: number; points: number; evidence: string };
const CRITERIA: [string, string][] = [
  ["industry_fit", "Industry fit"],
  ["company_size_fit", "Company size fit"],
  ["pain_point_fit", "Pain point fit"],
  ["signal_strength", "Buying signals"],
];

export default function LeadDetail() {
  const { id } = useParams();
  const lead = useAsync(() => api.get<Lead>(`/leads/${id}`), [id]);
  const action = useAction();
  const l = lead.data;

  async function step(label: string, path: string, success: string) {
    await action.run(label, () => api.post(path), success);
    await lead.reload();
  }

  async function processInBackground() {
    const job = await action.run("process", () => api.post<Job>(`/leads/${id}/process`));
    if (!job) return;
    action.setNotice("Pipeline queued. The worker runs Research → Qualify → Draft…");
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const current = await api.get<Job>(`/jobs/${job.id}`);
      if (current.status === "SUCCEEDED" || current.status === "FAILED") {
        action.setNotice(current.status === "SUCCEEDED" ? "Pipeline finished." : `Pipeline failed: ${current.last_error}`);
        break;
      }
    }
    await lead.reload();
  }

  if (lead.error) return <ErrorBanner error={lead.error} />;
  if (!l) return <p className="muted">Loading…</p>;
  const contact = l.contacts[0];
  const suppressed = l.status === "SUPPRESSED";
  const busy = !!action.busy;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{l.company_name} <Badge value={l.status} /></h1>
          <div className="muted">
            Campaign: {l.campaign.name} {l.website && <>· <a href={l.website} target="_blank" rel="noreferrer">{l.website}</a></>}
          </div>
        </div>
        <div className="actions">
          <button className="primary" disabled={busy || suppressed || l.disabled} onClick={processInBackground}>
            Run full pipeline
          </button>
          {l.disabled ? (
            <button disabled={busy} onClick={() => step("enable", `/leads/${id}/enable`, "Lead enabled.")}>Enable lead</button>
          ) : (
            <button disabled={busy || suppressed} onClick={() => step("disable", `/leads/${id}/disable`, "Lead disabled; follow-ups cancelled.")}>Disable lead</button>
          )}
        </div>
      </div>
      <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
      <Notice message={action.notice} />
      {action.busy && action.busy !== "process" && <div className="banner info">Working: {action.busy}… agents can take a few seconds.</div>}

      <div className="steps">
        <button disabled={busy || suppressed} onClick={() => step("research", `/leads/${id}/research`, "Research complete.")}>
          1 · {l.research ? "Re-run research" : "Research"}
        </button>
        <button disabled={busy || suppressed || !l.research} onClick={() => step("qualify", `/leads/${id}/qualify`, "Qualification complete.")}>
          2 · Qualify
        </button>
        <button disabled={busy || suppressed || !l.qualified || l.disabled}
                onClick={() => step("generate email", `/leads/${id}/generate-email`, "Draft ready for review.")}>
          3 · {l.emails.some((e) => e.sequence_number === 0) ? "Regenerate email" : "Generate email"}
        </button>
        {l.emails[0] && <Link className="button" to={`/emails/${l.emails[0].id}`}>4 · Review & send →</Link>}
      </div>

      <div className="grid-2">
        <ResearchCard lead={l} />
        <Card title="Qualification">
          {l.qualified === null ? <Empty>Not qualified yet.</Empty> : (
            <>
              <div className="score-row">
                <div className={`score ${l.qualified ? "good" : "bad"}`}>{l.qualification_score}</div>
                <div>
                  <b>{l.qualified ? "Qualified" : "Not qualified"}</b>
                  <p>{l.qualification_reason}</p>
                  {l.recommended_angle && <p><span className="muted">Recommended angle:</span> {l.recommended_angle}</p>}
                </div>
              </div>
              <table className="compact">
                <thead><tr><th>Criterion</th><th>Rating</th><th>Points</th><th>Evidence</th></tr></thead>
                <tbody>
                  {CRITERIA.map(([key, label]) => {
                    const c = l.qualification_breakdown?.[key] as Criterion | undefined;
                    return c ? (
                      <tr key={key}><td>{label}</td><td>{c.rating}</td><td>{c.points}/{c.weight}</td><td className="small">{c.evidence}</td></tr>
                    ) : null;
                  })}
                </tbody>
              </table>
              <p className="muted small">Score is computed by fixed weights from the ratings; threshold {String(l.qualification_breakdown?.threshold ?? "")}.</p>
            </>
          )}
        </Card>
      </div>

      <div className="grid-2">
        {contact && <ContactCard contact={contact} onChanged={lead.reload} />}
        <Card title="Emails">
          {l.emails.length === 0 && <Empty>No emails yet.</Empty>}
          <ul className="list">
            {l.emails.map((e) => (
              <li key={e.id}>
                <Link to={`/emails/${e.id}`}>{e.sequence_number === 0 ? "Initial email" : `Follow-up ${e.sequence_number}`}: {e.subject}</Link>
                <Badge value={e.status} />
              </li>
            ))}
          </ul>
          {l.followups.length > 0 && (
            <>
              <h3>Follow-up schedule</h3>
              <ul className="list">
                {l.followups.map((f) => (
                  <li key={f.id}>
                    <span>Step {f.sequence_number} · due {when(f.due_at)}{f.cancel_reason && <span className="muted small"> ({f.cancel_reason})</span>}</span>
                    <Badge value={f.status} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      </div>

      <div className="grid-2">
        <RepliesCard lead={l} onChanged={lead.reload} />
        <Card title="Timeline">
          <ul className="timeline">
            {l.timeline.map((t, i) => (
              <li key={i}><span className="muted small">{when(t.at)}</span> {t.description}</li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}

function ResearchCard({ lead }: { lead: Lead }) {
  const r = lead.research?.data;
  if (!r) return <Card title="Research"><Empty>Not researched yet.</Empty></Card>;
  const list = (title: string, items: string[]) => (
    <>
      <h3>{title}</h3>
      {items.length ? <ul>{items.map((i) => <li key={i}>{i}</li>)}</ul> : <p className="muted small">None found (not guessed).</p>}
    </>
  );
  return (
    <Card title={`Research · confidence ${r.confidence.toFixed(2)}`}>
      <p>{r.company_summary}</p>
      <dl className="facts">
        <dt>Industry</dt><dd className={r.industry === "unknown" ? "muted" : ""}>{r.industry}</dd>
        <dt>Company size</dt><dd className={r.company_size === "unknown" ? "muted" : ""}>{r.company_size}</dd>
      </dl>
      {list("Relevant signals", r.relevant_signals)}
      {list("Likely pain points (hypotheses)", r.likely_pain_points)}
      {list("Personalization points", r.personalization_points)}
      <h3>Sources</h3>
      {r.sources.length ? (
        <ul className="small">
          {r.sources.map((s, i) => (
            <li key={i}>{s.claim} — {s.url.startsWith("http") ? <a href={s.url} target="_blank" rel="noreferrer">{s.url}</a> : <span className="muted">{s.url}</span>}</li>
          ))}
        </ul>
      ) : <p className="muted small">No sources.</p>}
      {!!r.evidence_errors?.length && <p className="muted small">Research tool issues: {r.evidence_errors.join("; ")}</p>}
    </Card>
  );
}

function ContactCard({ contact, onChanged }: { contact: Contact; onChanged: () => void }) {
  const action = useAction();

  async function forget() {
    if (!window.confirm("Forget this person? Outreach stops permanently and their personal data is erased. This cannot be undone.")) return;
    await action.run("forget", () => api.post(`/contacts/${contact.id}/forget`), "Contact forgotten.");
    onChanged();
  }
  async function unsubscribe() {
    if (!window.confirm("Mark this contact as unsubscribed? They will never be emailed again.")) return;
    await action.run("unsubscribe", () => api.post(`/contacts/${contact.id}/unsubscribe`), "Contact unsubscribed.");
    onChanged();
  }

  return (
    <Card title="Contact">
      <ErrorBanner error={action.error} />
      <Notice message={action.notice} />
      {contact.forgotten_at ? (
        <p className="muted">This person asked to be forgotten on {when(contact.forgotten_at)}. Their personal data was erased; only a hashed suppression record remains so they are never contacted again.</p>
      ) : (
        <dl className="facts">
          <dt>Name</dt><dd>{contact.name ?? "—"}</dd>
          <dt>Role</dt><dd>{contact.role ?? "—"}</dd>
          <dt>Email</dt><dd>{contact.email}</dd>
        </dl>
      )}
      {contact.suppressed && <p><Badge value="SUPPRESSED" /> <span className="small">{contact.suppression_reason?.replace(/_/g, " ")}</span></p>}
      {!contact.forgotten_at && (
        <div className="actions">
          {!contact.suppressed && <button disabled={!!action.busy} onClick={unsubscribe}>Unsubscribe</button>}
          <button className="danger" disabled={!!action.busy} onClick={forget}>Forget Me</button>
        </div>
      )}
    </Card>
  );
}

function RepliesCard({ lead, onChanged }: { lead: Lead; onChanged: () => void }) {
  const sentEmails = lead.emails.filter((e) => ["SENT", "DELIVERED", "REPLIED", "COMPLETED"].includes(e.status));
  const [form, setForm] = useState({ email_id: "", body: "" });
  const action = useAction();
  const selectedEmailId = form.email_id || sentEmails[sentEmails.length - 1]?.id || "";

  async function submit(e: FormEvent) {
    e.preventDefault();
    const email_id = selectedEmailId;
    const ok = await action.run("reply", () => api.post(`/replies?analyze_now=true`, { email_id, body: form.body }), "Reply recorded and analyzed.");
    if (ok) setForm({ email_id: "", body: "" });
    onChanged();
  }

  return (
    <Card title="Replies">
      <ErrorBanner error={action.error} />
      <Notice message={action.notice} />
      {lead.replies.length === 0 && <Empty>No replies.</Empty>}
      {lead.replies.map((r) => (
        <div key={r.id} className="reply">
          <div className="reply-head">
            <Badge value={r.classification ?? "PENDING"} />
            {r.requires_human_attention && <span className="badge warn">needs attention</span>}
            <span className="muted small">{when(r.received_at)}</span>
          </div>
          <blockquote>{r.body}</blockquote>
          {r.summary && <p className="small">{r.summary}</p>}
          {r.recommended_action && <p className="small"><b>Next:</b> {r.recommended_action}</p>}
        </div>
      ))}
      {sentEmails.length > 0 && !lead.contacts[0]?.forgotten_at && (
        <form onSubmit={submit} className="stack">
          <h3>Log a reply</h3>
          <p className="muted small">Paste a reply you received. Replies also arrive automatically through the inbound email webhook.</p>
          <select value={selectedEmailId} onChange={(e) => setForm({ ...form, email_id: e.target.value })}>
            {sentEmails.map((e) => <option key={e.id} value={e.id}>{e.sequence_number === 0 ? "Initial" : `Follow-up ${e.sequence_number}`}: {e.subject}</option>)}
          </select>
          <textarea required rows={3} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} placeholder="Reply text…" />
          <button disabled={!!action.busy}>Record reply</button>
        </form>
      )}
    </Card>
  );
}
