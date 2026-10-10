"""Observability and operational endpoints: agent runs, jobs, follow-up processing."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, container, current_user
from app.db import get_db
from app.errors import InvalidStateError
from app.models import AgentRun, Followup, Job
from app.models.enums import FollowupStatus
from app.schemas import AgentRunOut, FollowupOut, JobOut
from app.services.common import get_owned
from app.services.container import Container
from app.services.followup_service import process_due_followups

router = APIRouter(tags=["system"])


@router.get("/agent-runs", response_model=list[AgentRunOut])
def list_agent_runs(lead_id: uuid.UUID | None = None, agent_name: str | None = None,
                    cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
                    limit: int = Query(100, le=500)):
    stmt = select(AgentRun).where(AgentRun.organization_id == cu.org_id).order_by(AgentRun.started_at.desc()).limit(limit)
    if lead_id:
        stmt = stmt.where(AgentRun.lead_id == lead_id)
    if agent_name:
        stmt = stmt.where(AgentRun.agent_name == agent_name)
    return db.scalars(stmt).all()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return get_owned(db, Job, job_id, cu.org_id)


@router.post("/followups/process")
def process_followups_now(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
                          c: Container = Depends(container)):
    """Process this organization's due follow-ups immediately (the worker also does this on a schedule)."""
    return {"outcomes": process_due_followups(db, c, organization_id=cu.org_id)}


@router.post("/followups/{followup_id}/retry", response_model=FollowupOut)
def retry_followup(followup_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    followup = get_owned(db, Followup, followup_id, cu.org_id, for_update=True)
    if followup.status != FollowupStatus.FAILED:
        raise InvalidStateError("Only failed follow-ups can be retried.")
    followup.status = FollowupStatus.PENDING
    followup.cancel_reason = None
    db.commit()
    return followup


@router.get("/system/status")
def system_status(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
                  c: Container = Depends(container)):
    """Live status for the top bar. Every value is counted from the database or read from configuration."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func

    from app.models import Approval, MemoryEntry, Workflow, WorkflowEvent
    from app.models.enums import ApprovalStatus, JobStatus, TraceStatus, WorkflowState

    now = datetime.now(timezone.utc)
    working = {WorkflowState.PENDING, WorkflowState.RESEARCHING, WorkflowState.QUALIFYING, WorkflowState.DRAFTING,
               WorkflowState.SAFETY_CHECK}
    org = cu.org_id
    count = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    running = count(select(func.count(Workflow.id)).where(Workflow.organization_id == org, Workflow.state.in_(working),
                                                          Workflow.updated_at >= now - timedelta(minutes=30)))
    agents_active = db.scalars(select(WorkflowEvent.agent).where(
        WorkflowEvent.organization_id == org, WorkflowEvent.completed_at >= now - timedelta(minutes=10)).distinct()).all()
    stuck = count(select(func.count(Job.id)).where(Job.organization_id == org, Job.status == JobStatus.QUEUED,
                                                   Job.run_at < now - timedelta(minutes=2)))
    from app.services.email_service import ensure_review_approvals

    ensure_review_approvals(db, org)
    s = c.settings
    return {
        "workflows_running": running,
        "agents_active_10m": sorted(agents_active),
        "pending_approvals": count(select(func.count(Approval.id)).where(Approval.organization_id == org,
                                                                         Approval.status == ApprovalStatus.PENDING)),
        "memory_entries": count(select(func.count(MemoryEntry.id)).where(MemoryEntry.organization_id == org)),
        "blocked_by_policy_7d": count(select(func.count(WorkflowEvent.id)).where(
            WorkflowEvent.organization_id == org, WorkflowEvent.status == TraceStatus.BLOCKED,
            WorkflowEvent.completed_at >= now - timedelta(days=7))),
        "jobs_waiting_for_worker": stuck,
        "providers": {"llm": s.llm_provider, "email": s.email_provider, "media": s.media_provider},
    }
