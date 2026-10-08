import { STATUS_LABEL, type Stage, fmtDuration } from "./agents";

const KIND_LABEL = { agent: "AI agent", human: "Human", rule: "Backend rule" };

/** Live execution panel: one row per stage with status, real result, duration and time. */
export function AgentActivity({ stages, live }: { stages: Stage[]; live?: boolean }) {
  return (
    <section className="card agent-activity">
      <header className="card-header">
        <h2>Agent activity</h2>
        <div className="actions">
          {live && <span className="live-dot">Live</span>}
          <span className="muted small">Agents recommend · rules &amp; humans decide</span>
        </div>
      </header>
      <ol className="activity-list">
        {stages.map((s) => (
          <li key={s.key} className={`activity-row st-${s.status}`}>
            <span className={`stage-icon kind-${s.kind}`} aria-hidden>
              {s.status === "completed" ? "✓" : s.status === "blocked" ? "✕" : s.status === "running" ? "" : s.kind === "human" ? "H" : s.kind === "rule" ? "§" : "AI"}
            </span>
            <div className="activity-main">
              <div className="activity-title">
                <b>{s.label}</b>
                <span className="muted small">{KIND_LABEL[s.kind]}</span>
              </div>
              <div className="activity-result">{s.result}</div>
            </div>
            <div className="activity-meta">
              <span className={`pill pill-${s.status}`}>{STATUS_LABEL[s.status]}</span>
              <span className="muted small">
                {fmtDuration(s.durationMs)}
                {s.durationMs != null && s.at ? " · " : ""}
                {s.at ? new Date(s.at).toLocaleTimeString() : ""}
              </span>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
