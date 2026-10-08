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
