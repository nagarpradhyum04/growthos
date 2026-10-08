import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, container, current_user
from app.db import get_db
from app.errors import GrowthOSError
from app.models import AgentRun, Campaign, Contact, Email, EmailReply, Followup, Lead
from app.models.enums import LeadStatus
from app.schemas import (
    CampaignOut,
    ContactOut,
    EmailOut,
    FollowupOut,
    JobOut,
    LeadCreate,
    LeadDetail,
    LeadListItem,
    QualificationOut,
    ReplyOut,
    ResearchOut,
    TimelineEvent,
)
from app.services import jobs, lead_service
from app.services.common import get_owned, latest_research
from app.services.container import Container

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("", response_model=list[LeadListItem])
def list_leads(campaign_id: uuid.UUID | None = None, status: LeadStatus | None = None,
               cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
               limit: int = Query(200, le=500)):
    stmt = (
        select(Lead, Campaign.name)
        .join(Campaign, Campaign.id == Lead.campaign_id)
        .where(Lead.organization_id == cu.org_id)
        .order_by(Lead.last_activity_at.desc())
        .limit(limit)
    )
    if campaign_id:
        stmt = stmt.where(Lead.campaign_id == campaign_id)
    if status:
        stmt = stmt.where(Lead.status == status)
    rows = db.execute(stmt).all()
    lead_ids = [lead.id for lead, _ in rows]
    contacts: dict[uuid.UUID, Contact] = {}
    if lead_ids:
        for c in db.scalars(select(Contact).where(Contact.lead_id.in_(lead_ids)).order_by(Contact.created_at.desc())):
            contacts[c.lead_id] = c  # oldest wins (primary contact)
    items = []
    for lead, campaign_name in rows:
        contact = contacts.get(lead.id)
        items.append(LeadListItem(
            id=lead.id, campaign_id=lead.campaign_id, campaign_name=campaign_name, company_name=lead.company_name,
            contact_name=contact.name if contact else None, contact_email=contact.email if contact else None,
            qualification_score=lead.qualification_score, qualified=lead.qualified, status=lead.status,
            disabled=lead.disabled, last_activity_at=lead.last_activity_at,
        ))
    return items


@router.post("", response_model=LeadDetail, status_code=201)
def create_lead(body: LeadCreate, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    lead = lead_service.create_lead(
        db, cu.org_id, campaign_id=body.campaign_id, company_name=body.company_name, website=body.website,
        notes=body.notes, contact_name=body.contact_name, contact_role=body.contact_role,
        contact_email=str(body.contact_email),
    )
    db.commit()
    return _detail(db, lead)


class ProspectIn(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    website: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=5000)
    contact_name: str = Field(default="", max_length=200)
    contact_role: str = Field(default="", max_length=200)
    contact_email: EmailStr


class BulkLeadsIn(BaseModel):
    campaign_id: uuid.UUID
    prospects: list[ProspectIn] = Field(min_length=1, max_length=200)


@router.post("/bulk", status_code=201)
def bulk_create(body: BulkLeadsIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Import a prospect list. Each row passes the same suppression/duplicate checks as a single lead."""
    results = []
    for p in body.prospects:
        try:
            with db.begin_nested():
                lead = lead_service.create_lead(db, cu.org_id, campaign_id=body.campaign_id,
                                                company_name=p.company_name, website=p.website, notes=p.notes,
                                                contact_name=p.contact_name, contact_role=p.contact_role,
                                                contact_email=str(p.contact_email))
            results.append({"company_name": p.company_name, "status": "created", "lead_id": str(lead.id)})
        except GrowthOSError as exc:
            results.append({"company_name": p.company_name, "status": "skipped", "reason": exc.message})
    db.commit()
    return {"created": sum(r["status"] == "created" for r in results), "results": results}


@router.get("/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return _detail(db, get_owned(db, Lead, lead_id, cu.org_id))


@router.post("/{lead_id}/research", response_model=ResearchOut)
def research(lead_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
             c: Container = Depends(container)):
    lead = get_owned(db, Lead, lead_id, cu.org_id)
    result = lead_service.research_lead(db, lead, c)
    db.commit()
    return result


@router.post("/{lead_id}/qualify", response_model=QualificationOut)
def qualify(lead_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
            c: Container = Depends(container)):
    lead = lead_service.qualify_lead(db, get_owned(db, Lead, lead_id, cu.org_id), c)
    db.commit()
    return QualificationOut(qualified=bool(lead.qualified), score=lead.qualification_score or 0,
                            reason=lead.qualification_reason or "", recommended_angle=lead.recommended_angle or "",
                            breakdown=lead.qualification_breakdown)


@router.post("/{lead_id}/generate-email", response_model=EmailOut)
def generate_email(lead_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
                   c: Container = Depends(container)):
    email = lead_service.generate_initial_email(db, get_owned(db, Lead, lead_id, cu.org_id), c)
    db.commit()
    return email


@router.post("/{lead_id}/process", response_model=JobOut, status_code=202)
def process(lead_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Queue the full Research -> Qualify -> Draft pipeline (run by the worker)."""
    lead = get_owned(db, Lead, lead_id, cu.org_id)
    job = jobs.enqueue(db, "process_lead", {"lead_id": str(lead.id)}, organization_id=cu.org_id,
                       dedupe_key=f"process_lead:{lead.id}")
    db.commit()
    return job


@router.post("/{lead_id}/disable", response_model=LeadDetail)
def disable(lead_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    lead = lead_service.set_lead_disabled(db, get_owned(db, Lead, lead_id, cu.org_id), True)
    db.commit()
    return _detail(db, lead)


@router.post("/{lead_id}/enable", response_model=LeadDetail)
def enable(lead_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    lead = lead_service.set_lead_disabled(db, get_owned(db, Lead, lead_id, cu.org_id), False)
    db.commit()
    return _detail(db, lead)


def _detail(db: Session, lead: Lead) -> LeadDetail:
    campaign = db.get(Campaign, lead.campaign_id)
    contacts = db.scalars(select(Contact).where(Contact.lead_id == lead.id).order_by(Contact.created_at)).all()
    research = latest_research(db, lead.id)
    emails = db.scalars(select(Email).where(Email.lead_id == lead.id).order_by(Email.sequence_number)).all()
    replies = db.scalars(select(EmailReply).where(EmailReply.lead_id == lead.id).order_by(EmailReply.received_at)).all()
    followups = db.scalars(select(Followup).where(Followup.lead_id == lead.id).order_by(Followup.sequence_number)).all()

    timeline = _timeline(db, lead, contacts, research, emails, replies, followups)

    return LeadDetail(
        id=lead.id, campaign=CampaignOut.model_validate(campaign), company_name=lead.company_name,
        website=lead.website, notes=lead.notes, status=lead.status, disabled=lead.disabled, qualified=lead.qualified,
        qualification_score=lead.qualification_score, qualification_reason=lead.qualification_reason,
        recommended_angle=lead.recommended_angle, qualification_breakdown=lead.qualification_breakdown,
        last_activity_at=lead.last_activity_at, created_at=lead.created_at,
        contacts=[ContactOut.model_validate(c) for c in contacts],
        research=ResearchOut.model_validate(research) if research else None,
        emails=[EmailOut.model_validate(e) for e in emails],
        replies=[ReplyOut.model_validate(r) for r in replies],
        followups=[FollowupOut.model_validate(f) for f in followups],
        timeline=timeline,
    )


AGENT_LABELS = {
    "research": "Research Agent", "qualification": "Qualification Agent", "outreach": "Outreach Agent",
    "followup": "Follow-up Agent", "reply_analysis": "Reply Analysis Agent", "analytics": "Analytics Agent",
}


def _timeline(db: Session, lead: Lead, contacts, research, emails, replies, followups) -> list[TimelineEvent]:
    """Activity history assembled from what is already stored (rows + agent_runs); nothing is invented."""
    ev = [TimelineEvent(at=lead.created_at, type="lead_created", description="Lead created", actor="human")]
    runs = db.scalars(select(AgentRun).where(AgentRun.lead_id == lead.id).order_by(AgentRun.started_at)).all()
    last_qualification = next((r for r in reversed(runs) if r.agent_name == "qualification"
                               and r.status.value == "SUCCEEDED"), None)
    for run in runs:
        at = run.completed_at or run.started_at
        name = AGENT_LABELS.get(run.agent_name, run.agent_name)
        if run.status.value == "FAILED":
            ev.append(TimelineEvent(at=at, type="agent_failed", actor="agent",
                                    description=f"{name} failed — nothing was saved ({(run.error or '')[:120]})"))
        elif run.status.value == "SUCCEEDED" and run.agent_name in ("research", "qualification"):
            text = f"{name} completed"
            if run.agent_name == "research" and research is not None and run.id == research.agent_run_id:
                text += f" (confidence {research.confidence:.2f})"
            if run is last_qualification and lead.qualification_score is not None:
                text += f": {lead.qualification_score}/100 — {'qualified' if lead.qualified else 'not qualified'}"
            ev.append(TimelineEvent(at=at, type=f"{run.agent_name}_completed", description=text, actor="agent"))
    if research is not None and research.agent_run_id is None:
        ev.append(TimelineEvent(at=research.created_at, type="research_completed", actor="agent",
                                description=f"Research completed (confidence {research.confidence:.2f})"))
    if lead.qualified is False and not any(e.sequence_number == 0 for e in emails):
        ev.append(TimelineEvent(at=lead.last_activity_at, type="outreach_blocked", actor="system",
                                description="No outreach: lead did not qualify"))
    for e in emails:
        label = "Initial email" if e.sequence_number == 0 else f"Follow-up {e.sequence_number}"
        writer = "Outreach Agent" if e.sequence_number == 0 else "Follow-up Agent"
        ev.append(TimelineEvent(at=e.created_at, type="email_drafted", actor="agent",
                                description=f"{label} draft generated by {writer}"))
        if e.approved_at:
            who = "human reviewer" if e.approved_by_user_id else "automated-sending setting"
            ev.append(TimelineEvent(at=e.approved_at, type="email_approved", actor="human" if e.approved_by_user_id else "system",
                                    description=f"{label} approved by {who}"))
        if e.sent_at:
            ev.append(TimelineEvent(at=e.sent_at, type="email_sent", actor="system",
                                    description=f"{label} passed the safety gate and was sent"))
        if e.status.value == "SUPPRESSED":
            ev.append(TimelineEvent(at=e.updated_at, type="email_blocked", actor="system",
                                    description=f"{label} blocked: contact suppressed"))
    for r in replies:
        ev.append(TimelineEvent(at=r.received_at, type="reply", actor="contact", description="Reply received"))
        if r.opt_out_detected:
            ev.append(TimelineEvent(at=r.received_at, type="opt_out_detected", actor="system",
                                    description="Opt-out language detected by deterministic rule — contact suppressed"))
        if r.analyzed_at and r.classification:
            by = "Reply Analysis Agent" if r.agent_run_id else "backend rules"
            ev.append(TimelineEvent(at=r.analyzed_at, type="reply_classified", actor="agent" if r.agent_run_id else "system",
                                    description=f"Reply classified as {r.classification.value.replace('_', ' ')} by {by}"))
    for f in followups:
        if f.status.value == "CANCELLED":
            ev.append(TimelineEvent(at=f.updated_at, type="followup_stopped", actor="system",
                                    description=f"Follow-up {f.sequence_number} stopped ({(f.cancel_reason or '').replace('_', ' ')})"))
        elif f.status.value == "LIMIT_REACHED":
            ev.append(TimelineEvent(at=f.updated_at, type="sequence_completed", actor="system",
                                    description="Follow-up limit reached — sequence completed, no more emails"))
        elif f.status.value == "FAILED":
            ev.append(TimelineEvent(at=f.updated_at, type="followup_failed", actor="system",
                                    description=f"Follow-up {f.sequence_number} generation failed"))
    for c in contacts:
        if c.forgotten_at:
            ev.append(TimelineEvent(at=c.forgotten_at, type="forgotten", actor="human",
                                    description="Forget Me: personal data erased, suppression kept"))
        elif c.suppressed:
            ev.append(TimelineEvent(at=c.updated_at, type="suppressed", actor="system",
                                    description=f"Contact suppressed ({(c.suppression_reason or '').replace('_', ' ')})"))
    ev.sort(key=lambda t: t.at)
    return ev
