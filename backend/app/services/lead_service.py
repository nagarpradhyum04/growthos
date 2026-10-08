"""Lead lifecycle: create, research, qualify, generate the initial email draft."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConflictError, InvalidStateError
from app.models import Campaign, Contact, Email, EmailDraft, Lead, ResearchResult
from app.models.enums import EmailStatus, LeadStatus
from app.services.agents import ResearchInput
from app.services.common import (
    business_profile_context,
    campaign_context,
    contact_context,
    get_owned,
    latest_research,
    lead_context,
    previous_interactions,
    qualification_context,
)
from app.services.container import Container
from app.services.llm.run_logger import RunContext
from app.services.suppression import hash_email, is_suppressed, normalize_email


def _touch(lead: Lead, status: LeadStatus | None = None) -> None:
    if status is not None and lead.status != LeadStatus.SUPPRESSED:
        lead.status = status
    lead.last_activity_at = datetime.now(timezone.utc)


def _ctx(lead: Lead) -> RunContext:
    return RunContext(organization_id=lead.organization_id, lead_id=lead.id, campaign_id=lead.campaign_id)


def primary_contact(db: Session, lead: Lead) -> Contact:
    contact = db.scalar(select(Contact).where(Contact.lead_id == lead.id).order_by(Contact.created_at))
    if contact is None:
        raise InvalidStateError("Lead has no contact")
    return contact


def create_lead(db: Session, organization_id: uuid.UUID, *, campaign_id: uuid.UUID, company_name: str,
                website: str, notes: str, contact_name: str, contact_role: str, contact_email: str) -> Lead:
    campaign = get_owned(db, Campaign, campaign_id, organization_id)
    email_hash = hash_email(contact_email)

    # Suppression is checked BEFORE storing anything: a person who asked to be forgotten must
    # not re-enter the system, even through a fresh import.
    if is_suppressed(db, organization_id, email_hash):
        raise ConflictError("This contact has opted out or asked to be forgotten and cannot be added.")
    duplicate = db.scalar(
        select(Contact.id)
        .join(Lead, Lead.id == Contact.lead_id)
        .where(Lead.campaign_id == campaign.id, Contact.email_hash == email_hash)
    )
    if duplicate:
        raise ConflictError("This contact is already in this campaign.")

    lead = Lead(organization_id=organization_id, campaign_id=campaign.id, company_name=company_name.strip(),
                website=website.strip(), notes=notes.strip())
    db.add(lead)
    db.flush()
    db.add(Contact(organization_id=organization_id, lead_id=lead.id, name=contact_name.strip() or None,
                   role=contact_role.strip() or None, email=normalize_email(contact_email), email_hash=email_hash))
    db.flush()
    return lead


def _ensure_workable(lead: Lead) -> None:
    if lead.status == LeadStatus.SUPPRESSED:
        raise InvalidStateError("Lead is suppressed; no further work is allowed.")


def research_lead(db: Session, lead: Lead, container: Container) -> ResearchResult:
    _ensure_workable(lead)
    contact = primary_contact(db, lead)
    result = container.research_agent().run(
        ResearchInput(company_name=lead.company_name, website=lead.website, contact_name=contact.name or "",
                      contact_role=contact.role or "", notes=lead.notes),
        _ctx(lead),
    )
    data = result.output.model_dump(mode="json")
    data["evidence_urls"] = sorted(result.evidence.urls)
    data["evidence_errors"] = result.evidence.errors
    research = ResearchResult(organization_id=lead.organization_id, lead_id=lead.id, agent_run_id=result.run_id,
                              data=data, confidence=result.output.confidence)
    db.add(research)
    if lead.status in (LeadStatus.NEW, LeadStatus.RESEARCHED):
        _touch(lead, LeadStatus.RESEARCHED)
    else:
        _touch(lead)
    db.flush()
    return research


def qualify_lead(db: Session, lead: Lead, container: Container) -> Lead:
    _ensure_workable(lead)
    research = latest_research(db, lead.id)
    if research is None:
        raise InvalidStateError("Research the lead before qualifying it.")
    campaign = db.get(Campaign, lead.campaign_id)
    result = container.qualification_agent().run(
        business_profile=business_profile_context(db, lead.organization_id),
        lead=lead_context(lead),
        research=research.data,
        campaign=campaign_context(campaign),
        ctx=_ctx(lead),
    ).result
    lead.qualified = result.qualified
    lead.qualification_score = result.score
    lead.qualification_reason = result.reason
    lead.recommended_angle = result.recommended_angle
    lead.qualification_breakdown = result.breakdown
    if lead.status in (LeadStatus.NEW, LeadStatus.RESEARCHED, LeadStatus.QUALIFIED, LeadStatus.DISQUALIFIED):
        _touch(lead, LeadStatus.QUALIFIED if result.qualified else LeadStatus.DISQUALIFIED)
    else:
        _touch(lead)
    db.flush()
    return lead


def generate_initial_email(db: Session, lead: Lead, container: Container) -> Email:
    _ensure_workable(lead)
    if lead.disabled:
        raise InvalidStateError("Lead is disabled.")
    if not lead.qualified:
        raise InvalidStateError("Only qualified leads get outreach drafts. Qualify the lead first.")
    contact = primary_contact(db, lead)
    if contact.suppressed:
        raise InvalidStateError("Contact is suppressed.")
    existing = db.scalar(
        select(Email).where(Email.campaign_id == lead.campaign_id, Email.contact_id == contact.id,
                            Email.sequence_number == 0).with_for_update()
    )
    if existing and existing.status not in (EmailStatus.DRAFT, EmailStatus.APPROVED, EmailStatus.FAILED):
        raise ConflictError("The initial email for this contact was already sent or closed.")

    research = latest_research(db, lead.id)
    campaign = db.get(Campaign, lead.campaign_id)
    result = container.outreach_agent().run(
        {
            "business_profile": business_profile_context(db, lead.organization_id),
            "lead": lead_context(lead),
            "contact": contact_context(contact),
            "research": research.data if research else None,
            "qualification": qualification_context(lead),
            "campaign": campaign_context(campaign),
            "previous_interactions": previous_interactions(db, contact.id),
        },
        _ctx(lead),
    )
    out = result.output
    draft = EmailDraft(organization_id=lead.organization_id, lead_id=lead.id, contact_id=contact.id,
                       agent_run_id=result.run_id, agent_name="outreach", sequence_number=0, subject=out.subject,
                       body=out.body, personalization_used=out.personalization_used, confidence=out.confidence)
    db.add(draft)
    db.flush()
    if existing is None:
        existing = Email(organization_id=lead.organization_id, campaign_id=lead.campaign_id, lead_id=lead.id,
                         contact_id=contact.id, sequence_number=0, subject=out.subject, body=out.body)
        db.add(existing)
    # Regenerating replaces the content and resets approval: a human must review again.
    existing.draft_id = draft.id
    existing.subject = out.subject
    existing.body = out.body
    existing.status = EmailStatus.DRAFT
    existing.approved_at = None
    existing.approved_by_user_id = None
    existing.edited_by_human = False
    _touch(lead, LeadStatus.DRAFTED if lead.status == LeadStatus.QUALIFIED else None)
    db.flush()
    return existing


def set_lead_disabled(db: Session, lead: Lead, disabled: bool) -> Lead:
    from app.services.suppression import cancel_pending_followups

    lead.disabled = disabled
    if disabled:
        for contact in db.scalars(select(Contact).where(Contact.lead_id == lead.id)):
            cancel_pending_followups(db, contact.id, "lead_disabled")
    _touch(lead)
    db.flush()
    return lead
