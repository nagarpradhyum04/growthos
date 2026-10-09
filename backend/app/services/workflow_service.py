"""Workflow state + agent trace (workflows / workflow_events).

The Orchestrator owns state transitions; other services report events into the lead's active
workflow through `advance_lead()` (sends, replies, follow-ups), so one trace covers the whole journey.
"""
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Workflow, WorkflowEvent
from app.models.enums import TERMINAL_WORKFLOW_STATES, TraceStatus, WorkflowState, WorkflowType


def now() -> datetime:
    return datetime.now(timezone.utc)


def start_workflow(db: Session, organization_id: uuid.UUID, workflow_type: WorkflowType, *, goal: str = "",
                   lead_id=None, campaign_id=None, customer_id=None, parent_id=None,
                   plan: list | None = None, command: str | None = None) -> Workflow:
    wf = Workflow(organization_id=organization_id, workflow_type=workflow_type, goal=goal, lead_id=lead_id, command=command,
                  campaign_id=campaign_id, customer_id=customer_id, parent_id=parent_id, plan=plan or [],
                  summary={}, state=WorkflowState.PENDING)
    db.add(wf)
    db.flush()
    return wf


def set_state(wf: Workflow, state: WorkflowState, error: str | None = None) -> None:
    wf.state = state
    if error:
        wf.error = error
    if state in TERMINAL_WORKFLOW_STATES:
        wf.completed_at = wf.completed_at or now()


def record(db: Session, wf: Workflow, agent: str, action: str, status: TraceStatus, result: str = "", *,
           detail: dict | None = None, state: WorkflowState | None = None, agent_run_id=None,
           started_at: datetime | None = None, duration_ms: int | None = None) -> WorkflowEvent:
    if state is not None:
        set_state(wf, state)
    finished = now()
    ev = WorkflowEvent(organization_id=wf.organization_id, workflow_id=wf.id, agent=agent, action=action,
                       status=status, result=result[:2000], detail=detail or {}, state_after=wf.state.value,
                       agent_run_id=agent_run_id, lead_id=wf.lead_id, started_at=started_at or finished,
                       completed_at=finished, duration_ms=duration_ms)
    db.add(ev)
    db.flush()
    return ev


class _Step:
    def __init__(self):
        self.status = TraceStatus.COMPLETED
        self.result = ""
        self.detail: dict = {}
        self.agent_run_id = None


@contextmanager
def step(db: Session, wf: Workflow, agent: str, action: str, *, state: WorkflowState | None = None):
    """Time a step and record it. Inside the block set s.result / s.status / s.detail.
    Exceptions are recorded as FAILED and re-raised."""
    if state is not None:
        set_state(wf, state)
        db.flush()
    started, t0 = now(), time.monotonic()
    s = _Step()
    try:
        yield s
    except Exception as exc:
        message = getattr(exc, "message", None) or type(exc).__name__
        record(db, wf, agent, action, TraceStatus.FAILED, message, detail=s.detail, started_at=started,
               duration_ms=int((time.monotonic() - t0) * 1000), agent_run_id=s.agent_run_id)
        raise
    record(db, wf, agent, action, s.status, s.result, detail=s.detail, started_at=started,
           duration_ms=int((time.monotonic() - t0) * 1000), agent_run_id=s.agent_run_id)


def active_lead_workflow(db: Session, lead_id: uuid.UUID) -> Workflow | None:
    return db.scalar(
        select(Workflow)
        .where(Workflow.lead_id == lead_id, Workflow.workflow_type == WorkflowType.LEAD)
        .order_by(Workflow.created_at.desc())
    )


def advance_lead(db: Session, lead, agent: str, action: str, status: TraceStatus, result: str = "", *,
                 state: WorkflowState | None = None, detail: dict | None = None) -> Workflow:
    """Report an event on a lead's journey; opens a LEAD workflow if none exists (e.g. manual steps)."""
    wf = active_lead_workflow(db, lead.id)
    if wf is None:
        wf = start_workflow(db, lead.organization_id, WorkflowType.LEAD, goal=f"Lead journey: {lead.company_name}",
                            lead_id=lead.id, campaign_id=lead.campaign_id)
    elif wf.state in TERMINAL_WORKFLOW_STATES and state not in TERMINAL_WORKFLOW_STATES and state is not None:
        wf.completed_at = None  # a later event (e.g. a reply) re-opens the journey
    record(db, wf, agent, action, status, result, state=state, detail=detail)
    return wf
