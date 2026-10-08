"""Small shared helpers for services."""
import uuid
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import InvalidStateError, NotFoundError
from app.models import BusinessProfile, Campaign, Contact, Email, EmailReply, Lead, ResearchResult
from app.models.enums import SENT_LIKE_STATUSES

M = TypeVar("M")


def get_owned(db: Session, model: type[M], obj_id: uuid.UUID, organization_id: uuid.UUID,
              *, for_update: bool = False) -> M:
    """Fetch a row by id, scoped to the organization. Another org's row is indistinguishable from
    a missing one (404), so ids can't be probed across tenants."""
    stmt = select(model).where(model.id == obj_id, model.organization_id == organization_id)
    if for_update:
        stmt = stmt.with_for_update()
    obj = db.scalar(stmt)
    if obj is None:
        raise NotFoundError(f"{model.__name__} not found")
    return obj


# ---------- context builders: the structured "memory" handed to agents ----------
def business_profile_context(db: Session, organization_id: uuid.UUID) -> dict:
    profile = db.scalar(select(BusinessProfile).where(BusinessProfile.organization_id == organization_id))
    if profile is None or not (profile.company_description or profile.products_services):
        raise InvalidStateError("Set up your business profile (description and products) first")
    return {
        "company_name": profile.company_name,
        "company_description": profile.company_description,
        "products_services": profile.products_services,
        "target_customers": profile.target_customers,
        "value_proposition": profile.value_proposition,
        "industries": profile.industries,
        "target_company_sizes": profile.target_company_sizes,
        "tone": profile.tone,
        "website": profile.website,
        "key_differentiators": profile.key_differentiators,
        "campaign_goals": profile.campaign_goals,
        "sender_name": profile.sender_name,
    }


def lead_context(lead: Lead) -> dict:
    return {"company_name": lead.company_name, "website": lead.website}


def contact_context(contact: Contact) -> dict:
    # Only what the writer needs. The email address is never sent to the LLM.
    return {"name": contact.name or "", "role": contact.role or ""}


def campaign_context(campaign: Campaign) -> dict:
    return {"name": campaign.name, "objective": campaign.objective, "target_audience": campaign.target_audience}


def latest_research(db: Session, lead_id: uuid.UUID) -> ResearchResult | None:
    return db.scalar(
        select(ResearchResult).where(ResearchResult.lead_id == lead_id).order_by(ResearchResult.created_at.desc())
    )


def qualification_context(lead: Lead) -> dict:
    return {
        "qualified": lead.qualified,
        "score": lead.qualification_score,
        "reason": lead.qualification_reason,
        "recommended_angle": lead.recommended_angle,
    }


def previous_interactions(db: Session, contact_id: uuid.UUID) -> list[dict]:
    emails = db.scalars(
        select(Email)
        .where(Email.contact_id == contact_id, Email.status.in_(SENT_LIKE_STATUSES))
        .order_by(Email.sequence_number)
    ).all()
    replies = db.scalars(select(EmailReply).where(EmailReply.contact_id == contact_id)).all()
    items = [{"type": "email_sent", "subject": e.subject, "body": e.body,
              "sent_at": e.sent_at.isoformat() if e.sent_at else None} for e in emails]
    items += [{"type": "reply", "classification": r.classification, "summary": r.summary} for r in replies]
    return items
