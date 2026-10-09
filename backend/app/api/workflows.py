"""Orchestrator workflows and the agent trace."""
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, container, current_user
from app.db import get_db
from app.models import Campaign, Lead, Workflow, WorkflowEvent
from app.errors import InvalidStateError
from app.models.enums import CampaignStatus, WorkflowType
from app.services import command_router
from app.services import jobs
from app.services import workflow_service as wfs
from app.services.common import get_owned
from app.services.container import Container
from app.services.orchestrator import Orchestrator

router = APIRouter(tags=["orchestrator"])


class GoalRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=1000)
    campaign_id: uuid.UUID | None = None  # only needed for "find customers" commands
    command: str | None = None  # optional explicit command key (e.g. from a suggestion chip)
    max_leads: int = Field(default=25, ge=1, le=100)


def event_dict(e: WorkflowEvent) -> dict:
    return {"id": str(e.id), "workflow_id": str(e.workflow_id), "agent": e.agent, "action": e.action,
            "status": e.status.value, "result": e.result, "detail": e.detail, "state_after": e.state_after,
            "lead_id": str(e.lead_id) if e.lead_id else None, "agent_run_id": str(e.agent_run_id) if e.agent_run_id else None,
            "started_at": e.started_at, "completed_at": e.completed_at, "duration_ms": e.duration_ms}


def workflow_dict(w: Workflow, company: str | None = None) -> dict:
    return {"id": str(w.id), "type": w.workflow_type.value, "goal": w.goal, "state": w.state.value,
            "command": w.command,
            "parent_id": str(w.parent_id) if w.parent_id else None, "lead_id": str(w.lead_id) if w.lead_id else None,
            "campaign_id": str(w.campaign_id) if w.campaign_id else None,
            "customer_id": str(w.customer_id) if w.customer_id else None, "plan": w.plan, "summary": w.summary,
            "error": w.error, "created_at": w.created_at, "updated_at": w.updated_at, "completed_at": w.completed_at,
            "company_name": company}


@router.get("/workflows/commands")
def list_commands(cu: CurrentUser = Depends(current_user)):
    """Commands the Orchestrator understands, with example phrasings for suggestions."""
    return [command_router.describe(cmd) for cmd in command_router.COMMANDS]


@router.get("/workflows/route")
def preview_route(text: str, cu: CurrentUser = Depends(current_user)):
    """Preview which workflow a command maps to (deterministic, no LLM)."""
    r = command_router.route(text)
    return {"command": command_router.describe(r.command) if r.command else None, "matched": r.matched,
            "alternatives": r.alternatives}


@router.post("/workflows/goal", status_code=202)
def start_goal(body: GoalRequest, run_now: bool = False, cu: CurrentUser = Depends(current_user),
               db: Session = Depends(get_db), c: Container = Depends(container)):
    """Give GrowthOS a command. The Orchestrator maps it to a known workflow and runs it in the background.
    Several commands can run at the same time; each gets its own workflow and trace."""
    cmd = command_router.BY_KEY.get(body.command or "") or command_router.route(body.goal).command
    if cmd is None:
        raise InvalidStateError(
            "I couldn't map that to something GrowthOS can safely do. Try one of the suggestions.",
            details={"suggestions": [e for c_ in command_router.COMMANDS for e in c_.examples[:1]]})
    campaign_id = None
    if cmd.needs_campaign:
        if body.campaign_id:
            campaign_id = get_owned(db, Campaign, body.campaign_id, cu.org_id).id
        else:
            campaign_id = db.scalar(select(Campaign.id).where(Campaign.organization_id == cu.org_id,
                                                              Campaign.status == CampaignStatus.ACTIVE)
                                    .order_by(Campaign.created_at.desc()))
            if campaign_id is None:
                raise InvalidStateError("Create an active campaign with prospects first.")
    wf = wfs.start_workflow(db, cu.org_id, WorkflowType.GOAL, goal=body.goal.strip(), campaign_id=campaign_id,
                            plan=list(cmd.plan), command=cmd.key)
    db.commit()
    if run_now:
        Orchestrator(db, c).run_command(wf, body.max_leads)
    else:
        jobs.enqueue(db, "run_goal", {"workflow_id": str(wf.id), "max_leads": body.max_leads},
                     organization_id=cu.org_id, dedupe_key=f"goal:{wf.id}")
        db.commit()
    return workflow_dict(wf)


@router.get("/workflows")
def list_workflows(workflow_type: WorkflowType | None = None, lead_id: uuid.UUID | None = None,
                   customer_id: uuid.UUID | None = None, top_level: bool = False,
                   limit: int = Query(50, le=200), cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    stmt = (select(Workflow, Lead.company_name).outerjoin(Lead, Lead.id == Workflow.lead_id)
            .where(Workflow.organization_id == cu.org_id).order_by(Workflow.updated_at.desc()).limit(limit))
    if workflow_type:
        stmt = stmt.where(Workflow.workflow_type == workflow_type)
    if lead_id:
        stmt = stmt.where(Workflow.lead_id == lead_id)
    if customer_id:
        stmt = stmt.where(Workflow.customer_id == customer_id)
    if top_level:
        stmt = stmt.where(Workflow.parent_id.is_(None))
    return [workflow_dict(w, company) for w, company in db.execute(stmt).all()]


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    wf = get_owned(db, Workflow, workflow_id, cu.org_id)
    events = db.scalars(select(WorkflowEvent).where(WorkflowEvent.workflow_id == wf.id)
                        .order_by(WorkflowEvent.started_at, WorkflowEvent.created_at)).all()
    children = db.execute(select(Workflow, Lead.company_name).outerjoin(Lead, Lead.id == Workflow.lead_id)
                          .where(Workflow.parent_id == wf.id).order_by(Workflow.created_at)).all()
    company = db.get(Lead, wf.lead_id).company_name if wf.lead_id and db.get(Lead, wf.lead_id) else None
    # Agents of a goal run work inside sub-workflows (one per lead, or one per stage of a full cycle), so the
    # orchestration view needs their recorded events too (two levels down).
    ids = [w.id for w, _ in children]
    if ids:
        ids += db.scalars(select(Workflow.id).where(Workflow.parent_id.in_(ids))).all()
    sub_events = db.scalars(select(WorkflowEvent).where(WorkflowEvent.workflow_id.in_(ids))
                            .order_by(WorkflowEvent.started_at, WorkflowEvent.created_at).limit(2000)).all() if ids else []
    return {**workflow_dict(wf, company), "events": [event_dict(e) for e in events],
            "sub_events": [event_dict(e) for e in sub_events],
            "children": [workflow_dict(w, n) for w, n in children]}


@router.get("/trace")
def recent_trace(limit: int = Query(40, le=200), lead_id: uuid.UUID | None = None,
                 cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Latest agent trace events across all workflows (Command Center feed)."""
    stmt = (select(WorkflowEvent, Workflow.workflow_type, Workflow.goal, Lead.company_name)
            .join(Workflow, Workflow.id == WorkflowEvent.workflow_id)
            .outerjoin(Lead, Lead.id == WorkflowEvent.lead_id)
            .where(WorkflowEvent.organization_id == cu.org_id)
            .order_by(WorkflowEvent.created_at.desc()).limit(limit))
    if lead_id:
        stmt = stmt.where(WorkflowEvent.lead_id == lead_id)
    return [{**event_dict(e), "workflow_type": t.value, "goal": g, "company_name": n}
            for e, t, g, n in db.execute(stmt).all()]
