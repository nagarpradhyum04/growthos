import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, container, current_user
from app.db import get_db
from app.models import Campaign, Contact, Email, EmailReply, Followup, Lead
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

    timeline = [TimelineEvent(at=lead.created_at, type="lead_created", description="Lead created")]
    if research:
        timeline.append(TimelineEvent(at=research.created_at, type="researched",
                                      description=f"Researched (confidence {research.confidence:.2f})"))
    for e in emails:
        label = "Initial email" if e.sequence_number == 0 else f"Follow-up {e.sequence_number}"
        timeline.append(TimelineEvent(at=e.created_at, type="email_drafted", description=f"{label} drafted"))
        if e.sent_at:
            timeline.append(TimelineEvent(at=e.sent_at, type="email_sent", description=f"{label} sent"))
    for r in replies:
        timeline.append(TimelineEvent(at=r.received_at, type="reply",
                                      description=f"Reply received ({r.classification or 'not analyzed yet'})"))
    for f in followups:
        if f.status.value in ("CANCELLED", "LIMIT_REACHED", "FAILED"):
            timeline.append(TimelineEvent(at=f.updated_at, type="followup_" + f.status.value.lower(),
                                          description=f"Follow-up {f.sequence_number} {f.status.value.lower()}"
                                          + (f" ({f.cancel_reason})" if f.cancel_reason else "")))
    for c in contacts:
        if c.forgotten_at:
            timeline.append(TimelineEvent(at=c.forgotten_at, type="forgotten", description="Contact forgotten (Forget Me)"))
    timeline.sort(key=lambda t: t.at)

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
