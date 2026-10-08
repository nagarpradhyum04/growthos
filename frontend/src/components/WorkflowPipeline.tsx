import type { Stage } from "./agents";

const NODE_LABEL: Record<string, string> = {
  research: "Research",
  qualification: "Qualification",
  outreach: "Personalization / Outreach",
  human_review: "Human Review",
  safety: "Safety Check",
  send: "Send",
  reply_analysis: "Reply Analysis",
  followup: "Follow-up",
};

const STATE_TEXT = {
  completed: "Completed",
  running: "Active",
  waiting: "Waiting",
  blocked: "Blocked",
  pending: "Not started",
};

/** Orchestration view of the lead's journey. States come from the same derived stages as Agent Activity. */
export function WorkflowPipeline({ stages }: { stages: Stage[] }) {
  const nodes = stages.filter((s) => s.key in NODE_LABEL);
  return (
    <section className="card">
      <header className="card-header">
        <h2>Orchestration workflow</h2>
        <div className="legend small">
          {(["completed", "running", "waiting", "blocked", "pending"] as const).map((k) => (
            <span key={k}><i className={`dot dot-${k}`} />{STATE_TEXT[k]}</span>
          ))}
        </div>
      </header>
      <div className="workflow">
        {nodes.map((s, i) => (
          <div key={s.key} className="wf-step">
            <div className={`wf-node wf-${s.status} kind-${s.kind}`} title={s.result}>
              <div className="wf-kind">{s.kind === "agent" ? "AI agent" : s.kind === "human" ? "Human" : "Rule"}</div>
              <div className="wf-name">{NODE_LABEL[s.key]}</div>
              <div className="wf-state">{STATE_TEXT[s.status]}</div>
            </div>
            {i < nodes.length - 1 && <div className={`wf-arrow ${s.status === "completed" ? "done" : ""}`} aria-hidden>→</div>}
          </div>
        ))}
      </div>
    </section>
  );
}
