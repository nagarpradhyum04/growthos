// Agent metadata and pure helpers that turn REAL backend state (agent_runs, lead, emails, replies,
// follow-ups, send_check) into display stages. Nothing here decides business rules or invents results.
import type { AgentRun, EmailReview, LeadDetail } from "../types";

export const AGENTS: Record<string, { label: string; short: string; role: string }> = {
  research: { label: "Research Agent", short: "R", role: "Gathers public evidence and cites sources" },
  qualification: { label: "Qualification Agent", short: "Q", role: "Rates fit with evidence; backend computes the score" },
  outreach: { label: "Outreach Agent", short: "O", role: "Drafts a personalized email from verified research" },
  reply_analysis: { label: "Reply Analysis Agent", short: "A", role: "Classifies replies and recommends next steps" },
  followup: { label: "Follow-up Agent", short: "F", role: "Writes follow-ups when the backend allows one" },
  analytics: { label: "Analytics Agent", short: "M", role: "Explains metrics that actually exist" },
};

export type StageStatus = "pending" | "running" | "completed" | "waiting" | "blocked";

export interface Stage {
  key: string;
  label: string;
  kind: "agent" | "human" | "rule";
  status: StageStatus;
  result: string;
  durationMs?: number | null;
  at?: string | null;
}

export const STATUS_LABEL: Record<StageStatus, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  waiting: "Waiting",
  blocked: "Blocked",
};

const SENT = ["SENT", "DELIVERED", "REPLIED", "COMPLETED"];

export function latestRun(runs: AgentRun[], agent: string): AgentRun | undefined {
  return runs
    .filter((r) => r.agent_name === agent)
    .sort((a, b) => b.started_at.localeCompare(a.started_at))[0];
}

/** One-line, data-backed summary of an agent run's structured output. */
export function summarizeRun(run: AgentRun): string {
  if (run.status === "RUNNING") return "Working…";
  if (run.status === "FAILED") return `Failed: ${run.error ?? "unknown error"} — nothing was saved`;
  const o = run.output ?? {};
  const str = (k: string) => (typeof o[k] === "string" ? (o[k] as string) : "");
  switch (run.agent_name) {
    case "research": {
      const signals = Array.isArray(o.relevant_signals) ? o.relevant_signals.length : 0;
      const sources = Array.isArray(o.sources) ? o.sources.length : 0;
      return run.output
        ? `${fmtUnknown(str("industry"))} · ${fmtUnknown(str("company_size"))} · ${signals} signal(s), ${sources} source(s)`
        : "Completed (output not retained)";
    }
    case "qualification": {
      const keys = ["industry_fit", "company_size_fit", "pain_point_fit", "signal_strength"];
      const ratings = keys.map((k) => (o[k] as { rating?: string } | undefined)?.rating).filter(Boolean);
      return ratings.length ? `Ratings: ${ratings.join(" / ")}` : "Completed";
    }
    case "outreach":
    case "followup":
      return str("subject") ? `Drafted “${str("subject")}”` : "Draft generated";
    case "reply_analysis":
      return str("classification") ? `Classified: ${str("classification").replace(/_/g, " ")}` : "Classified";
    case "analytics":
      return str("summary") ? str("summary").slice(0, 110) : "Insights generated";
    default:
      return "Completed";
  }
}

export function fmtUnknown(value: string | null | undefined): string {
  return !value || value.toLowerCase() === "unknown" ? "Unknown" : value;
}

function fromRun(run: AgentRun | undefined, result?: string): Pick<Stage, "status" | "result" | "durationMs" | "at"> {
  if (!run) return { status: "pending", result: "Not run yet" };
  if (run.status === "RUNNING") return { status: "running", result: "Working…", at: run.started_at };
  if (run.status === "FAILED") return { status: "blocked", result: summarizeRun(run), durationMs: run.latency_ms, at: run.completed_at };
  return { status: "completed", result: result ?? summarizeRun(run), durationMs: run.latency_ms, at: run.completed_at };
}

/**
 * Pipeline stages for one lead, derived from stored state.
 * `review` is the initial email's review payload (includes the backend's send_check), if an email exists.
 */
export function leadStages(lead: LeadDetail, runs: AgentRun[], review: EmailReview | null, orgRuns: AgentRun[] = []): Stage[] {
  const initial = lead.emails.find((e) => e.sequence_number === 0);
  const suppressed = lead.status === "SUPPRESSED";
  const stages: Stage[] = [];

  // 1. Research
  const research = fromRun(latestRun(runs, "research"));
  if (research.status === "pending" && lead.research) {
    Object.assign(research, { status: "completed", result: `Confidence ${lead.research.confidence.toFixed(2)}`, at: lead.research.created_at });
  } else if (research.status === "completed" && lead.research) {
    research.result = `${fmtUnknown(lead.research.data.industry)} · ${fmtUnknown(lead.research.data.company_size)} · confidence ${lead.research.confidence.toFixed(2)}`;
  }
  stages.push({ key: "research", label: "Research Agent", kind: "agent", ...research });

  // 2. Qualification
  const qRun = latestRun(runs, "qualification");
  const qual = fromRun(qRun);
  if (qual.status === "completed" && lead.qualification_score !== null) {
    qual.result = `${lead.qualification_score}/100 — ${lead.qualified ? "Qualified" : "Disqualified"}`;
  } else if (qual.status === "pending" && lead.qualified !== null) {
    Object.assign(qual, { status: "completed", result: `${lead.qualification_score}/100 — ${lead.qualified ? "Qualified" : "Disqualified"}` });
  } else if (qual.status === "pending" && !lead.research) {
    qual.result = "Waits for research";
  }
  stages.push({ key: "qualification", label: "Qualification Agent", kind: "agent", ...qual });

  // 3. Outreach
  const out = fromRun(latestRun(runs, "outreach"));
  if (lead.qualified === false) Object.assign(out, { status: "blocked", result: "Not qualified — GrowthOS does not write outreach" });
  else if (out.status === "completed" && initial) out.result = `Drafted “${initial.subject}”`;
  else if (out.status === "completed" && !initial) out.result = "Draft was rejected by reviewer";
  else if (out.status === "pending" && initial) Object.assign(out, { status: "completed", result: `Drafted “${initial.subject}”` });
  else if (out.status === "pending") out.result = lead.qualified ? "Ready to draft" : "Waits for qualification";
  stages.push({ key: "outreach", label: "Outreach Agent", kind: "agent", ...out });

  // 4. Human review
  let human: Pick<Stage, "status" | "result" | "at">;
  if (!initial) human = { status: lead.qualified === false ? "blocked" : "pending", result: lead.qualified === false ? "Nothing to review" : "No draft yet" };
  else if (initial.status === "SUPPRESSED") human = { status: "blocked", result: "Draft blocked: contact suppressed" };
  else if (initial.approved_at) human = { status: "completed", result: initial.edited_by_human ? "Edited & approved by a human" : "Approved by a human", at: initial.approved_at };
  else human = { status: "waiting", result: "Waiting for human review — AI never sends on its own" };
  stages.push({ key: "human_review", label: "Human Review", kind: "human", ...human });

  // 5. Safety check (backend can_send)
  let safety: Pick<Stage, "status" | "result" | "at">;
  if (initial && SENT.includes(initial.status)) safety = { status: "completed", result: "Passed — send gate allowed this email", at: initial.sent_at };
  else if (!review || !initial) safety = { status: "pending", result: "Runs before every send" };
  else if (review.send_check.allowed) safety = { status: "completed", result: "All rules pass — ready to send" };
  else {
    const failing = review.send_check.checks.filter((c) => !c.passed && c.key !== "send_gate");
    const onlyApproval = failing.length === 1 && failing[0].key === "human_approved";
    safety = onlyApproval
      ? { status: "waiting", result: "Waiting for human approval" }
      : { status: "blocked", result: `SEND BLOCKED: ${failing.map((c) => c.label).join("; ")}` };
  }
  stages.push({ key: "safety", label: "Safety Check", kind: "rule", ...safety });

  // 6. Send (workflow only)
  let send: Pick<Stage, "status" | "result" | "at">;
  if (initial && SENT.includes(initial.status)) send = { status: "completed", result: `Sent ${new Date(initial.sent_at!).toLocaleString()}`, at: initial.sent_at };
  else if (initial?.status === "SCHEDULED") send = { status: "waiting", result: `Scheduled for ${initial.scheduled_for}` };
  else if (initial?.status === "FAILED") send = { status: "blocked", result: `Provider failed: ${initial.last_error ?? ""}` };
  else if (suppressed || safety.status === "blocked") send = { status: "blocked", result: "Not sent" };
  else send = { status: "pending", result: "Not sent" };
  stages.push({ key: "send", label: "Send", kind: "rule", ...send });

  // 7. Reply analysis
  const reply = lead.replies[lead.replies.length - 1];
  let ra: Pick<Stage, "status" | "result" | "durationMs" | "at">;
  if (reply?.classification) {
    const run = latestRun(runs, "reply_analysis");
    ra = {
      status: "completed",
      result: `${reply.classification.replace(/_/g, " ")}${reply.opt_out_detected ? " (opt-out rule)" : ""}`,
      durationMs: reply.agent_run_id ? run?.latency_ms : null,
      at: reply.analyzed_at,
    };
  } else if (reply) ra = { status: "running", result: "Reply received — analysis queued", at: reply.received_at };
  else if (initial && SENT.includes(initial.status)) ra = { status: "waiting", result: "Waiting for a reply" };
  else ra = { status: "pending", result: "No reply yet" };
  stages.push({ key: "reply_analysis", label: "Reply Analysis Agent", kind: "agent", ...ra });

  // 8. Follow-up
  const fus = lead.followups;
  const pendingFu = fus.find((f) => f.status === "PENDING");
  const cancelled = [...fus].reverse().find((f) => f.status === "CANCELLED");
  const limit = fus.find((f) => f.status === "LIMIT_REACHED");
  const fuRun = latestRun(runs, "followup");
  let fu: Pick<Stage, "status" | "result" | "durationMs" | "at">;
  if (limit) fu = { status: "completed", result: "Sequence finished — follow-up limit reached", at: limit.due_at };
  else if (cancelled && !pendingFu) fu = { status: "blocked", result: `Stopped by rule: ${(cancelled.cancel_reason ?? "").replace(/[_:]/g, " ")}` };
  else if (fuRun?.status === "RUNNING") fu = { status: "running", result: "Writing follow-up…" };
  else if (pendingFu) fu = { status: "waiting", result: `Follow-up ${pendingFu.sequence_number} due ${new Date(pendingFu.due_at).toLocaleString()}` };
  else if (fus.some((f) => f.status === "GENERATED")) fu = { ...fromRun(fuRun), result: "Follow-up drafted — awaiting review" };
  else fu = { status: "pending", result: "Scheduled after send" };
  stages.push({ key: "followup", label: "Follow-up Agent", kind: "agent", ...fu });

  // 9. Analytics (organization-level)
  const an = latestRun(orgRuns, "analytics");
  stages.push({
    key: "analytics",
    label: "Analytics Agent",
    kind: "agent",
    ...(an ? fromRun(an) : { status: "pending" as StageStatus, result: "Runs on demand (Analytics page)" }),
  });

  if (suppressed) {
    for (const s of stages) {
      if (s.key !== "analytics" && (s.status === "pending" || s.status === "waiting")) {
        s.status = "blocked";
        s.result = "Stopped: contact suppressed";
      }
    }
  }
  return stages;
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.max(s, 0)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
