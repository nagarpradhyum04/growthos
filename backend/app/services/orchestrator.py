"""Orchestrator ("Boss Agent"): coordinates the specialist agents and owns workflow state.

It routes deterministically (no LLM decides what happens next), reads/writes shared memory, retries
safe (transient) failures once, runs the Safety Agent (policy layer), escalates to humans, and records a
trace event for every step. It never sends email itself — sending only happens via email_service.send_email,
behind can_send() and human approval.
"""
import time
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AgentFailedError, GrowthOSError
from app.models import Campaign, Email, Lead, Workflow
from app.models.enums import (
    ApprovalType,
    LeadStatus,
    Priority,
    TraceStatus,
    WorkflowState,
    WorkflowType,
)
from app.services import approval_service, lead_service, memory_service
from app.services import workflow_service as wfs
from app.services.common import latest_research
from app.services.container import Container
from app.services.policy import evaluate_outbound

LEAD_PLAN = ["research", "qualification", "memory", "outreach", "safety", "human_review"]
GOAL_PLAN = ["understand_goal", "select_candidates", "research", "qualification", "outreach", "safety",
             "human_review", "summarize"]


@dataclass
class StepResult:
    step: str
    status: str  # done | skipped | stopped | failed
    detail: str = ""


@dataclass
class WorkflowResult:
    lead_id: str
    steps: list[StepResult] = field(default_factory=list)
    lead_status: str = ""
    email_id: str | None = None
    workflow_id: str | None = None
    state: str = ""
    safety: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _retryable(exc: AgentFailedError) -> bool:
    cause = exc.__cause__
    return bool(getattr(cause, "retryable", False))


class Orchestrator:
    def __init__(self, db: Session, container: Container):
        self.db = db
        self.container = container

    # ------------------------------------------------------------------ lead workflow
    def process_lead(self, lead: Lead, *, force: bool = False, parent: Workflow | None = None) -> WorkflowResult:
        """Lead -> Research -> Qualification -> (memory) -> Outreach -> Safety -> Human review."""
        db = self.db
        wf = wfs.start_workflow(db, lead.organization_id, WorkflowType.LEAD, goal=f"Acquire {lead.company_name}",
                                lead_id=lead.id, campaign_id=lead.campaign_id,
                                parent_id=parent.id if parent else None, plan=LEAD_PLAN)
        wfs.record(db, wf, "orchestrator", "Plan workflow", TraceStatus.COMPLETED,
                   "Research → Qualify → Read memory → Draft → Safety check → Human review", detail={"plan": LEAD_PLAN})
        db.commit()
        result = WorkflowResult(lead_id=str(lead.id), workflow_id=str(wf.id))

        def finish(state: WorkflowState | None = None) -> WorkflowResult:
            if state is not None:
                wfs.set_state(wf, state)
            db.commit()
            result.lead_status = lead.status.value
            result.state = wf.state.value
            return result

        if lead.status == LeadStatus.SUPPRESSED or lead.disabled:
            wfs.record(db, wf, "safety", "Pre-flight check", TraceStatus.BLOCKED,
                       "Lead is suppressed or disabled — no agent will act on it", state=WorkflowState.BLOCKED)
            result.steps.append(StepResult("guard", "stopped", "Lead is suppressed or disabled"))
            return finish()

        # 1. Research (+ write shared memory)
        if latest_research(db, lead.id) is None or force:
            research = self._agent_step(wf, result, "research", "Research company", WorkflowState.RESEARCHING,
                                        lambda: lead_service.research_lead(db, lead, self.container),
                                        lambda r: f"{r.data.get('industry')} · {r.data.get('company_size')} · "
                                                  f"{len(r.data.get('relevant_signals', []))} signal(s), "
                                                  f"{len(r.data.get('sources', []))} source(s), confidence {r.confidence:.2f}")
            if research is None:
                return finish(WorkflowState.FAILED)
            self._store_research_memory(wf, lead, research)
        else:
            wfs.record(db, wf, "research", "Research company", TraceStatus.SKIPPED,
                       "Reused existing research (no repeat agent call)", state=WorkflowState.RESEARCHING)
            result.steps.append(StepResult("research", "skipped", "Research already exists"))

        # 2. Qualification
        if lead.qualified is None or force:
            done = self._agent_step(wf, result, "qualification", "Score lead", WorkflowState.QUALIFYING,
                                    lambda: lead_service.qualify_lead(db, lead, self.container),
                                    lambda l: f"{l.qualification_score}/100 — {'qualified' if l.qualified else 'not qualified'} "
                                              "(score computed by deterministic rules)")
            if done is None:
                return finish(WorkflowState.FAILED)
        else:
            wfs.record(db, wf, "qualification", "Score lead", TraceStatus.SKIPPED,
                       f"Already scored {lead.qualification_score}/100", state=WorkflowState.QUALIFYING)
            result.steps.append(StepResult("qualification", "skipped", "Already qualified"))
        memory_service.remember(db, lead.organization_id, scope="lead", subject_id=lead.id, category="result",
                                key="qualification", content=f"Scored {lead.qualification_score}/100 "
                                f"({'qualified' if lead.qualified else 'not qualified'}): {lead.qualification_reason}",
                                source="qualification", workflow_id=wf.id)
        if not lead.qualified:
            wfs.record(db, wf, "orchestrator", "Decide next step", TraceStatus.COMPLETED,
                       f"Stop: not qualified (score {lead.qualification_score}). No outreach will be written.",
                       state=WorkflowState.COMPLETED, detail={"outcome": "disqualified"})
            result.steps.append(StepResult("outreach", "stopped", f"Not qualified (score {lead.qualification_score})"))
            return finish()

        # 3. Read shared memory for the writer
        ctx = memory_service.lead_context(db, lead)
        wfs.record(db, wf, "memory", "Load shared memory for Outreach Agent", TraceStatus.COMPLETED,
                   f"{len(ctx['lead_facts'])} lead fact(s), {len(ctx['learned_insights'])} learned insight(s)",
                   detail={"insights": [i["content"] for i in ctx["learned_insights"]]})

        # 4. Outreach draft
        email = db.scalar(select(Email).where(Email.lead_id == lead.id, Email.sequence_number == 0))
        if email is None:
            email = self._agent_step(wf, result, "outreach", "Draft personalized email", WorkflowState.DRAFTING,
                                     lambda: lead_service.generate_initial_email(db, lead, self.container),
                                     lambda e: f"Drafted “{e.subject}”")
            if email is None:
                return finish(WorkflowState.FAILED)
        else:
            wfs.record(db, wf, "outreach", "Draft personalized email", TraceStatus.SKIPPED,
                       f"Draft already exists: “{email.subject}”", state=WorkflowState.DRAFTING)
            result.steps.append(StepResult("outreach", "skipped", "Initial email already exists"))
        result.email_id = str(email.id)

        # 5. Safety Agent (deterministic policy layer)
        self.safety_and_route(wf, lead, email, result)
        return finish()

    def safety_and_route(self, wf: Workflow, lead: Lead, email: Email, result: WorkflowResult | None = None) -> str:
        """Run the Safety Agent on a draft and route it: BLOCK, or a human approval (ALLOW/ESCALATE)."""
        db = self.db
        t0 = time.monotonic()
        decision = evaluate_outbound(db, email)
        ms = int((time.monotonic() - t0) * 1000)
        status = {"ALLOW": TraceStatus.COMPLETED, "BLOCK": TraceStatus.BLOCKED, "ESCALATE": TraceStatus.ESCALATED}[decision.outcome]
        wfs.record(db, wf, "safety", "Check draft against safety & policy rules", status,
                   f"{decision.outcome}: {decision.explain()}", state=WorkflowState.SAFETY_CHECK,
                   detail=decision.to_dict(), duration_ms=ms)
        if result is not None:
            result.safety = decision.to_dict()
            result.steps.append(StepResult("safety", "done" if decision.outcome != "BLOCK" else "stopped",
                                           decision.explain()))
        if decision.outcome == "BLOCK":
            wfs.set_state(wf, WorkflowState.BLOCKED, decision.explain())
            return "blocked"

        reasons = ["First-touch outreach always requires human approval (policy)"] if email.sequence_number == 0 \
            else ["Follow-ups require approval while automated sending is off"]
        if decision.outcome == "ESCALATE":
            reasons.append(decision.explain())
        approval_service.create(
            db, lead.organization_id, ApprovalType.OUTBOUND_EMAIL,
            title=f"Review email to {lead.company_name}: “{email.subject}”",
            reason="Escalated because: " + "; ".join(reasons),
            priority=Priority.HIGH if decision.outcome == "ESCALATE" else Priority.MEDIUM,
            category="outbound_email", recommended_action="Review the draft and its evidence, then approve & send or reject.",
            email_id=email.id, lead_id=lead.id, workflow_id=wf.id)
        wfs.record(db, wf, "human", "Human review", TraceStatus.WAITING,
                   "Waiting for the business owner to approve, edit or reject", state=WorkflowState.AWAITING_APPROVAL)
        if result is not None:
            result.steps.append(StepResult("human_review", "done", "Waiting for approval"))
        return "awaiting_approval"

    # ------------------------------------------------------------------ goal workflow
    def run_goal(self, wf: Workflow, max_leads: int = 25) -> dict:
        """Business goal -> plan -> fan out lead workflows over the campaign's prospects -> summary."""
        db = self.db
        campaign = db.get(Campaign, wf.campaign_id)
        insights = memory_service.learned_insights(db, wf.organization_id)
        wfs.record(db, wf, "orchestrator", "Understand goal", TraceStatus.COMPLETED,
                   f"Goal “{wf.goal}” → customer acquisition plan for campaign “{campaign.name}”: "
                   "research → qualify → personalize → safety → human review",
                   detail={"plan": GOAL_PLAN}, state=WorkflowState.PENDING)
        wfs.record(db, wf, "memory", "Read shared memory", TraceStatus.COMPLETED,
                   f"{len(insights)} learned insight(s) from past campaigns will guide the Outreach Agent",
                   detail={"insights": [i.content for i in insights]})
        candidates = db.scalars(
            select(Lead).where(Lead.campaign_id == campaign.id, Lead.disabled.is_(False),
                               Lead.status.in_([LeadStatus.NEW, LeadStatus.RESEARCHED, LeadStatus.QUALIFIED]))
            .order_by(Lead.created_at).limit(max_leads)).all()
        wfs.record(db, wf, "orchestrator", "Select prospects", TraceStatus.COMPLETED,
                   f"{len(candidates)} prospect(s) in “{campaign.name}” not yet contacted",
                   detail={"lead_ids": [str(l.id) for l in candidates]})
        db.commit()
        if not candidates:
            wfs.record(db, wf, "orchestrator", "Finish", TraceStatus.COMPLETED,
                       "Nothing to do: add prospects to the campaign first", state=WorkflowState.COMPLETED)
            db.commit()
            return {"leads": 0}

        stats = {"leads": len(candidates), "researched": 0, "qualified": 0, "disqualified": 0, "drafted": 0,
                 "safety_passed": 0, "safety_escalated": 0, "safety_blocked": 0, "awaiting_approval": 0, "failed": 0}
        timings: dict[str, int] = {}
        wfs.set_state(wf, WorkflowState.RESEARCHING)
        db.commit()
        for lead in candidates:
            t0 = time.monotonic()
            r = Orchestrator(db, self.container).process_lead(lead, parent=wf)
            timings[str(lead.id)] = int((time.monotonic() - t0) * 1000)
            steps = {s.step: s for s in r.steps}
            if steps.get("research") and steps["research"].status in ("done", "skipped"):
                stats["researched"] += 1
            if lead.qualified:
                stats["qualified"] += 1
            elif lead.qualified is False:
                stats["disqualified"] += 1
            if r.email_id:
                stats["drafted"] += 1
            outcome = (r.safety or {}).get("outcome")
            stats["safety_passed"] += outcome == "ALLOW"
            stats["safety_escalated"] += outcome == "ESCALATE"
            stats["safety_blocked"] += outcome == "BLOCK"
            stats["awaiting_approval"] += r.state == WorkflowState.AWAITING_APPROVAL.value
            stats["failed"] += r.state == WorkflowState.FAILED.value

        total_ms = sum(timings.values())
        wfs.record(db, wf, "research", "Research prospects", TraceStatus.COMPLETED,
                   f"Researched {stats['researched']} of {stats['leads']} prospect(s)", state=WorkflowState.QUALIFYING)
        wfs.record(db, wf, "qualification", "Score prospects", TraceStatus.COMPLETED,
                   f"{stats['qualified']} qualified, {stats['disqualified']} not qualified (deterministic scoring)",
                   state=WorkflowState.DRAFTING)
        wfs.record(db, wf, "outreach", "Write personalized drafts", TraceStatus.COMPLETED,
                   f"Generated {stats['drafted']} personalized draft(s)", state=WorkflowState.SAFETY_CHECK)
        wfs.record(db, wf, "safety", "Check every draft", TraceStatus.COMPLETED if not stats["safety_blocked"] else TraceStatus.BLOCKED,
                   f"{stats['safety_passed']} passed, {stats['safety_escalated']} escalated, {stats['safety_blocked']} blocked")
        final = WorkflowState.AWAITING_APPROVAL if stats["awaiting_approval"] else (
            WorkflowState.FAILED if stats["failed"] == stats["leads"] else WorkflowState.COMPLETED)
        wfs.record(db, wf, "human", "Route to business owner", TraceStatus.WAITING if stats["awaiting_approval"] else TraceStatus.SKIPPED,
                   f"{stats['awaiting_approval']} email(s) waiting for your approval" if stats["awaiting_approval"]
                   else "Nothing needs approval", state=final, duration_ms=total_ms)
        wf.summary = stats
        db.commit()
        return stats

    # ------------------------------------------------------------------ helpers
    def _agent_step(self, wf: Workflow, result: WorkflowResult, step: str, action: str, state: WorkflowState,
                    fn, summarize):
        """Run one specialist agent step; retry once on transient failures; record the trace."""
        db = self.db
        for attempt in (1, 2):
            wfs.set_state(wf, state)
            db.commit()
            t0 = time.monotonic()
            started = wfs.now()
            try:
                value = fn()
                db.commit()
            except AgentFailedError as exc:
                db.rollback()
                wf = db.merge(wf)
                if attempt == 1 and _retryable(exc):
                    wfs.record(db, wf, step, action, TraceStatus.RETRYING, f"Transient failure ({exc.message}); retrying once",
                               started_at=started, duration_ms=int((time.monotonic() - t0) * 1000))
                    db.commit()
                    continue
                wfs.record(db, wf, step, action, TraceStatus.FAILED, f"{exc.message} — nothing was saved",
                           started_at=started, duration_ms=int((time.monotonic() - t0) * 1000), state=WorkflowState.FAILED,
                           detail={"run_id": exc.details.get("run_id")})
                wfs.set_state(wf, WorkflowState.FAILED, exc.message)
                db.commit()
                result.steps.append(StepResult(step, "failed", exc.message))
                return None
            except GrowthOSError as exc:
                db.rollback()
                wf = db.merge(wf)
                wfs.record(db, wf, step, action, TraceStatus.FAILED, exc.message, started_at=started,
                           duration_ms=int((time.monotonic() - t0) * 1000), state=WorkflowState.FAILED)
                db.commit()
                result.steps.append(StepResult(step, "failed", exc.message))
                return None
            run_id = getattr(value, "agent_run_id", None)
            wfs.record(db, wf, step, action, TraceStatus.COMPLETED, summarize(value), started_at=started,
                       duration_ms=int((time.monotonic() - t0) * 1000), agent_run_id=run_id)
            db.commit()
            result.steps.append(StepResult(step, "done"))
            return value
        return None

    def _store_research_memory(self, wf: Workflow, lead: Lead, research) -> None:
        d = research.data
        facts = {
            "industry": d.get("industry"), "company_size": d.get("company_size"),
            "signals": "; ".join(d.get("relevant_signals", [])), "pain_points": "; ".join(d.get("likely_pain_points", [])),
        }
        stored = 0
        for key, value in facts.items():
            if value and value != "unknown":
                memory_service.remember(self.db, lead.organization_id, scope="lead", subject_id=lead.id,
                                        category="research", key=key, content=str(value), source="research",
                                        workflow_id=wf.id, data={"confidence": research.confidence})
                stored += 1
        wfs.record(self.db, wf, "memory", "Write research to shared memory", TraceStatus.COMPLETED,
                   f"Stored {stored} verified fact(s) for other agents" if stored else "Nothing verifiable to store")
        self.db.commit()
