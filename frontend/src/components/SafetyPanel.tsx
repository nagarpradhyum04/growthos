import type { SendCheck } from "../types";

/** Renders the backend's can_send() result. It never evaluates rules itself. */
export function SafetyPanel({ check, sent }: { check: SendCheck; sent?: boolean }) {
  const blockedOnlyByApproval =
    !check.allowed && check.reasons.length > 0 && check.reasons.every((r) => r === "not_approved");
  const state = sent ? "sent" : check.allowed ? "ok" : blockedOnlyByApproval ? "waiting" : "blocked";
  const headline = {
    sent: "Email already sent — it passed the safety gate",
    ok: "SAFE TO SEND — all rules pass",
    waiting: "WAITING FOR HUMAN APPROVAL",
    blocked: "SEND BLOCKED",
  }[state];
  return (
    <div className={`safety-panel safety-${state}`}>
      <div className="safety-head">
        <b>{headline}</b>
        <span className="small">Checked by backend <code>can_send()</code> · the UI cannot override it</span>
      </div>
      {!sent && (
        <ul className="checklist">
          {check.checks.map((c) => (
            <li key={c.key} className={c.passed ? "pass" : "fail"}>
              <span aria-hidden>{c.passed ? "✓" : "✕"}</span> {c.label}
              {!c.passed && c.reasons.length > 0 && <span className="reason"> — {c.reasons.map((r) => r.replace(/_/g, " ")).join(", ")}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
