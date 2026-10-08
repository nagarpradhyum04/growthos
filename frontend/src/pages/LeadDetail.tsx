import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { AgentActivity } from "../components/AgentActivity";
import { fmtUnknown, leadStages } from "../components/agents";
import { SafetyPanel } from "../components/SafetyPanel";
import { Timeline } from "../components/Timeline";
import { Badge, Card, Empty, ErrorBanner, Notice, when } from "../components/ui";
import { useAction, useAsync } from "../components/useAsync";
import { WorkflowPipeline } from "../components/WorkflowPipeline";
import { describeError } from "../api";
import { TraceFeed } from "../components/trace";
import type { AgentRun, Contact, CustomerRow, EmailReview, Job, LeadDetail as Lead, MemoryItem, ProductRow, ResearchData, TraceEvent } from "../types";

type Criterion = { rating: string; weight: number; points: number; evidence: string };
const CRITERIA: [string, string][] = [
  ["industry_fit", "Industry fit"],
  ["company_size_fit", "Company size"],
  ["pain_point_fit", "Pain point fit"],
  ["signal_strength", "Signal strength"],
];

interface State {
  lead: Lead;
  runs: AgentRun[];
  orgRuns: AgentRun[];
  review: EmailReview | null;
  trace: TraceEvent[];
  memory: MemoryItem[];
}

export default function LeadDetail() {
  const { id } = useParams();
  const [state, setState] = useState<State | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const action = useAction();
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const [lead, runs, orgRuns, trace, memory] = await Promise.all([
        api.get<Lead>(`/leads/${id}`),
        api.get<AgentRun[]>(`/agent-runs?lead_id=${id}&limit=100`),
        api.get<AgentRun[]>(`/agent-runs?agent_name=analytics&limit=1`),
        api.get<TraceEvent[]>(`/trace?lead_id=${id}&limit=100`),
        api.get<MemoryItem[]>(`/memory?scope=lead&subject_id=${id}`),
      ]);
      const initial = lead.emails.find((e) => e.sequence_number === 0);
      const review = initial ? await api.get<EmailReview>(`/emails/${initial.id}`) : null;
      if (alive.current) {
        setState({ lead, runs, orgRuns, review, trace: [...trace].reverse(), memory });
        setLoadError(null);
      }
    } catch (err) {
      if (alive.current) setLoadError(describeError(err));
    }
  }, [id]);

  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
    };
  }, [load]);

  async function step(label: string, path: string, success: string) {
    await action.run(label, () => api.post(path), success);
    await load();
  }

  /** Queue the orchestrator job and watch real agent_runs/lead state update while the worker runs it. */
  async function runPipeline() {
    const job = await action.run("process", () => api.post<Job>(`/leads/${id}/process`));
    if (!job) return;
    setLive(true);
    action.setNotice("Pipeline queued — the worker's orchestrator is running the agents…");
    try {
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const [current] = await Promise.all([api.get<Job>(`/jobs/${job.id}`), load()]);
        if (current.status === "SUCCEEDED" || current.status === "FAILED") {
          const steps = (current.result?.steps as { step: string; status: string; detail: string }[] | undefined) ?? [];
          const stopped = steps.find((s) => s.status === "stopped" || s.status === "failed");
          action.setNotice(
            current.status === "FAILED"
              ? `Pipeline failed: ${current.last_error}`
              : stopped
                ? `Pipeline stopped at ${stopped.step}: ${stopped.detail}`
                : "Pipeline finished — draft is waiting for your review.",
          );
          break;
        }
        if (i === 10 && current.status === "QUEUED") {
          action.setNotice("Still queued… is the worker running? (python -m app.worker)");
        }
      }
    } finally {
      setLive(false);
      await load();
    }
  }

  if (loadError && !state) return <ErrorBanner error={loadError} />;
  if (!state) return <p className="muted">Loading…</p>;
  const { lead: l, runs, review } = state;
  const stages = leadStages(l, runs, review, state.orgRuns);
  const contact = l.contacts[0];
  const suppressed = l.status === "SUPPRESSED";
  const busy = !!action.busy || live;
  const initial = l.emails.find((e) => e.sequence_number === 0);

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{l.company_name} <Badge value={l.status} />{l.disabled && <Badge value="BLOCKED" />}</h1>
          <div className="muted">
            Campaign: {l.campaign.name} {l.website && <>· <a href={l.website} target="_blank" rel="noreferrer">{l.website}</a></>}
          </div>
        </div>
        <div className="actions">
          <button className="primary" disabled={busy || suppressed || l.disabled} onClick={runPipeline}>
            {live ? "Running…" : "▶ Run full pipeline"}
          </button>
          {l.disabled ? (
            <button disabled={busy} onClick={() => step("enable", `/leads/${id}/enable`, "Lead enabled.")}>Enable lead</button>
          ) : (
            <button disabled={busy || suppressed} onClick={() => step("disable", `/leads/${id}/disable`, "Lead disabled; follow-ups cancelled.")}>Disable lead</button>
          )}
        </div>
      </div>
      <ErrorBanner error={action.error ?? loadError} onClose={() => action.setError(null)} />
      <Notice message={action.notice} />
      {action.busy && action.busy !== "process" && <div className="banner info">Working: {action.busy}… agents can take a few seconds.</div>}

      <WorkflowPipeline stages={stages} />

      <div className="grid-main">
        <div className="stack-lg">
          <div className="steps">
            <span className="muted small">Run agents step by step:</span>
            <button disabled={busy || suppressed} onClick={() => step("research", `/leads/${id}/research`, "Research complete.")}>
              1 · {l.research ? "Re-run research" : "Research"}
            </button>
            <button disabled={busy || suppressed || !l.research} onClick={() => step("qualify", `/leads/${id}/qualify`, "Qualification complete.")}>
              2 · Qualify
            </button>
            <button disabled={busy || suppressed || !l.qualified || l.disabled}
                    onClick={() => step("generate email", `/leads/${id}/generate-email`, "Draft ready for review.")}>
              3 · {initial ? "Regenerate email" : "Generate email"}
            </button>
            {initial && <Link className="button" to={`/emails/${initial.id}`}>4 · Human review →</Link>}
          </div>
          <ResearchCard lead={l} personalizationUsed={review?.personalization_used ?? []} />
          <QualificationCard lead={l} />
        </div>
        <AgentActivity stages={stages.filter((s) => s.key !== "send")} live={live} />
      </div>

      {initial && review && (
        <Card title="Human review & safety gate"
              actions={<Link className="button primary-outline" to={`/emails/${initial.id}`}>Open email review →</Link>}>
          <p className="small">
            <Badge value={initial.status} /> <b>{initial.subject}</b>
            {review.draft_confidence !== null && <span className="muted"> · Outreach Agent confidence {review.draft_confidence.toFixed(2)}</span>}
          </p>
          <SafetyPanel check={review.send_check} sent={["SENT", "DELIVERED", "REPLIED", "COMPLETED"].includes(initial.status)} />
        </Card>
      )}

      <div className="grid-2">
        {contact && <ContactCard contact={contact} onChanged={load} />}
        <Card title="Emails & follow-up schedule">
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
              <h3>Follow-up schedule (max {l.campaign.max_followups ?? "default"})</h3>
              <ul className="list">
                {l.followups.map((f) => (
                  <li key={f.id}>
                    <span>Step {f.sequence_number} · due {when(f.due_at)}{f.cancel_reason && <span className="muted small"> ({f.cancel_reason.replace(/[_:]/g, " ")})</span>}</span>
                    <Badge value={f.status} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Agent trace" actions={<Link to={`/workflows?lead=${l.id}`}>Workflows →</Link>}>
          <TraceFeed events={state.trace} compact />
        </Card>
        <div>
          <Card title="Shared memory" actions={<span className="muted small">written &amp; read by agents</span>}>
            {state.memory.length === 0 && <p className="empty">Nothing stored for this lead yet.</p>}
            <ul className="memory-list">
              {state.memory.map((m) => <li key={m.id}><span className={`mem-cat cat-${m.category}`}>{m.key}</span> {m.content}<div className="muted small">by {m.source}</div></li>)}
            </ul>
          </Card>
          <ConvertCard lead={l} onDone={load} />
        </div>
      </div>

      <div className="grid-2">
        <RepliesCard lead={l} onChanged={load} />
        <Card title="Activity timeline">
          <Timeline events={l.timeline} />
        </Card>
      </div>
    </>
  );
}

function Unknown({ value }: { value: string | null | undefined }) {
  const v = fmtUnknown(value);
  return <span className={v === "Unknown" ? "unknown" : ""}>{v}</span>;
}

function sourceFor(r: ResearchData, text: string) {
  const t = text.toLowerCase();
  return r.sources.find((s) => s.claim.toLowerCase().includes(t) || t.includes(s.claim.toLowerCase()));
}

function SourceLink({ url }: { url: string }) {
  return url.startsWith("http") ? (
    <a href={url} target="_blank" rel="noreferrer" className="source-link">{url.replace(/^https?:\/\//, "")}</a>
  ) : (
    <span className="source-link muted">{url === "user-notes" ? "your lead notes" : url}</span>
  );
}

function ResearchCard({ lead, personalizationUsed }: { lead: Lead; personalizationUsed: string[] }) {
  const r = lead.research?.data;
  if (!r) return <Card title="Research intelligence"><Empty>Not researched yet. The Research Agent only uses public evidence and marks anything unverifiable as Unknown.</Empty></Card>;
  const used = new Set(personalizationUsed.map((p) => p.toLowerCase()));
  const conf = r.confidence;
  const list = (title: string, items: string[], opts: { cite?: boolean; highlight?: boolean } = {}) => (
    <div>
      <h3>{title}</h3>
      {items.length ? (
        <ul className="evidence-list">
          {items.map((i) => {
            const src = opts.cite ? sourceFor(r, i) : undefined;
            const isUsed = opts.highlight && used.has(i.toLowerCase());
            return (
              <li key={i} className={isUsed ? "used" : ""}>
                {isUsed && <span className="used-tag">✓ used in email</span>}
                {i}
                {src && <> <SourceLink url={src.url} /></>}
              </li>
            );
          })}
        </ul>
      ) : <p className="unknown small">Unknown — not found in evidence (not guessed)</p>}
    </div>
  );
  return (
    <Card title="Research intelligence" actions={
      <span className={`confidence ${conf >= 0.6 ? "high" : conf >= 0.35 ? "mid" : "low"}`}>Confidence {conf.toFixed(2)}</span>
    }>
      <p>{r.company_summary}</p>
      <dl className="facts">
        <dt>Industry</dt><dd><Unknown value={r.industry} /></dd>
        <dt>Company size</dt><dd><Unknown value={r.company_size} /></dd>
      </dl>
      {personalizationUsed.length > 0 && (
        <div className="personalization-box">
          <h3>Personalization used in the email</h3>
          <ul>
            {personalizationUsed.map((p) => {
              const src = sourceFor(r, p);
              return <li key={p}>✓ {p} {src ? <SourceLink url={src.url} /> : <span className="muted small">(from research summary)</span>}</li>;
            })}
          </ul>
        </div>
      )}
      <div className="grid-2 tight">
        {list("Growth / buying signals", r.relevant_signals, { cite: true, highlight: true })}
        {list("Personalization points", r.personalization_points, { cite: true, highlight: true })}
      </div>
      {list("Likely pain points (hypotheses)", r.likely_pain_points)}
      <h3>Sources & evidence</h3>
      {r.sources.length ? (
        <ol className="sources">
          {r.sources.map((s, i) => <li key={i}><span>“{s.claim}”</span> <SourceLink url={s.url} /></li>)}
        </ol>
      ) : <p className="unknown small">No sources — no claims were made.</p>}
      {!!r.evidence_urls?.length && <p className="muted small">Evidence fetched: {r.evidence_urls.join(", ")}</p>}
      {!!r.evidence_errors?.length && <p className="muted small">Research tool issues: {r.evidence_errors.join("; ")}</p>}
    </Card>
  );
}

function QualificationCard({ lead: l }: { lead: Lead }) {
  if (l.qualified === null) return <Card title="Qualification"><Empty>Not qualified yet.</Empty></Card>;
  const b = l.qualification_breakdown ?? {};
  const rows = CRITERIA.map(([key, label]) => [key, label, b[key] as Criterion | undefined] as const).filter(([, , c]) => c);
  const total = rows.reduce((sum, [, , c]) => sum + (c?.points ?? 0), 0);
  const max = rows.reduce((sum, [, , c]) => sum + (c?.weight ?? 0), 0);
  const unknown = rows.filter(([, , c]) => c?.rating === "unknown").map(([, label]) => label);
  const disqualifiers = (b.disqualifiers as string[] | undefined) ?? [];
  const threshold = b.threshold as number | undefined;
  return (
    <Card title="Explainable qualification" actions={<Badge value={l.qualified ? "QUALIFIED" : "DISQUALIFIED"} />}>
      <div className="score-row">
        <div className={`score ${l.qualified ? "good" : "bad"}`}>{l.qualification_score}<span>/100</span></div>
        <div>
          <b>{l.qualified ? "Why this lead qualified" : "Why this lead was not contacted"}</b>
          <p>{l.qualification_reason}</p>
          {l.recommended_angle && <p><span className="muted">Recommended angle:</span> {l.recommended_angle}</p>}
        </div>
      </div>
      {rows.length > 0 && (
        <table className="score-table">
          <tbody>
            {rows.map(([key, label, c]) => (
              <tr key={key}>
                <td>{label}</td>
                <td className="bar-cell">
                  <div className="bar-track" title={`${c!.points} of ${c!.weight}`}>
                    <div className={`bar-fill r-${c!.rating}`} style={{ width: `${(c!.points / c!.weight) * 100}%` }} />
                  </div>
                </td>
                <td className="num">{c!.points}/{c!.weight}</td>
                <td><span className={`rating r-${c!.rating}`}>{c!.rating}</span></td>
                <td className="small">{c!.evidence}</td>
              </tr>
            ))}
            <tr className="total-row">
              <td>Total</td><td /><td className="num">{Math.round(total)}/{max}</td>
              <td colSpan={2} className="small muted">{threshold !== undefined && <>Threshold {threshold} → {l.qualified ? "qualified" : "not qualified"}</>}</td>
            </tr>
          </tbody>
        </table>
      )}
      {disqualifiers.length > 0 && (
        <div className="banner error"><span><b>Disqualifier:</b> {disqualifiers.join("; ")} — overrides the score.</span></div>
      )}
      {unknown.length > 0 && <p className="small"><span className="unknown">Unknown fields:</span> {unknown.join(", ")} — scored low rather than guessed.</p>}
      <p className="rule-note">
        § The Qualification Agent only rates each criterion (strong / partial / none / unknown) with evidence.
        The score is computed by fixed backend weights (strong 100%, partial 50%, unknown 20%, none 0%) — the LLM never picks the number.
      </p>
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
      {contact.suppressed && <p><Badge value="SUPPRESSED" /> <span className="small">{contact.suppression_reason?.replace(/_/g, " ")} — all outreach blocked by backend rules</span></p>}
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
    <Card title="Replies" actions={<Link to="/replies">All replies →</Link>}>
      <ErrorBanner error={action.error} />
      <Notice message={action.notice} />
      {lead.replies.length === 0 && <Empty>No replies.</Empty>}
      {lead.replies.map((r) => (
        <div key={r.id} className="reply">
          <div className="reply-head">
            <Badge value={r.classification ?? "PENDING"} />
            {r.opt_out_detected && <span className="badge bad">opt-out rule triggered</span>}
            {r.requires_human_attention && <span className="badge warn">needs human</span>}
            <span className="muted small">{when(r.received_at)}</span>
          </div>
          <blockquote>{r.body}</blockquote>
          {r.summary && <p className="small">{r.summary}</p>}
          {r.recommended_action && <p className="small"><b>→</b> {r.recommended_action}</p>}
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

function ConvertCard({ lead, onDone }: { lead: Lead; onDone: () => void }) {
  const products = useAsync(() => api.get<ProductRow[]>("/products"));
  const [form, setForm] = useState({ product_id: "", quantity: 1, order_value: "", serial_number: "" });
  const action = useAction();
  const navigate = useNavigate();
  if (lead.status === "CONVERTED") return <Card title="Customer"><p className="small"><Badge value="CONVERTED" /> This lead is now a customer. <Link to="/customers">Customers →</Link></p></Card>;
  if (lead.status === "SUPPRESSED") return null;
  async function convert(e: FormEvent) {
    e.preventDefault();
    const c = await action.run("convert", () => api.post<CustomerRow>(`/leads/${lead.id}/convert`, {
      product_id: form.product_id || null, quantity: form.quantity, serial_number: form.serial_number,
      order_value: form.order_value ? Number(form.order_value) : null,
    }));
    if (c) { onDone(); navigate(`/customers/${c.id}`); }
  }
  return (
    <Card title="Close the deal" actions={<span className="muted small">owner decision</span>}>
      <ErrorBanner error={action.error} />
      <p className="small muted">When the deal is won, convert this lead into a customer. Their history moves into customer memory and they can use the portal.</p>
      <form className="inline-form" onSubmit={convert}>
        <select value={form.product_id} onChange={(e) => setForm({ ...form, product_id: e.target.value })}>
          <option value="">No purchase yet</option>
          {products.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <input type="number" min={1} value={form.quantity} onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) })} style={{ width: 70 }} />
        <input placeholder="Order value" value={form.order_value} onChange={(e) => setForm({ ...form, order_value: e.target.value })} style={{ width: 110 }} />
        <button className="primary" disabled={!!action.busy}>Convert to customer</button>
      </form>
    </Card>
  );
}
