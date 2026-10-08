"""can_send(): the single gate every outgoing email must pass. No code path sends without it.

The LLM has no way to influence this function: it only reads database state.
"""
from dataclasses import dataclass, field

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Campaign, Contact, Email, EmailReply, Lead
from app.models.enums import SENT_LIKE_STATUSES, CampaignStatus, EmailStatus
from app.services.suppression import is_suppressed

# Reasons that mean the person must never be emailed (vs. temporary blocks like a paused campaign).
SUPPRESSION_REASONS = {"contact_suppressed", "contact_unsubscribed", "suppression_record_exists"}


@dataclass
class SendDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def suppressed(self) -> bool:
        return bool(SUPPRESSION_REASONS & set(self.reasons))


def max_followups_for(campaign: Campaign) -> int:
    return campaign.max_followups if campaign.max_followups is not None else get_settings().max_followups


def followup_delay_days_for(campaign: Campaign) -> int:
    if campaign.followup_delay_days is not None:
        return campaign.followup_delay_days
    return get_settings().followup_delay_days


def contact_has_replied(db: Session, contact_id, campaign_id) -> bool:
    return db.scalar(
        select(exists().where(EmailReply.contact_id == contact_id, EmailReply.campaign_id == campaign_id))
    )


def followup_limit_reached(email: Email, campaign: Campaign) -> bool:
    return email.sequence_number > max_followups_for(campaign)


def duplicate_email_exists(db: Session, email: Email, contact: Contact) -> bool:
    """Same person (by email hash, so duplicate contact rows are caught too), same campaign, same
    sequence step, already sent."""
    return db.scalar(
        select(
            exists().where(
                Email.id != email.id,
                Email.campaign_id == email.campaign_id,
                Email.sequence_number == email.sequence_number,
                Email.status.in_(SENT_LIKE_STATUSES),
                Email.contact_id == Contact.id,
                Contact.email_hash == contact.email_hash,
            )
        )
    )


def previous_step_sent(db: Session, email: Email) -> bool:
    if email.sequence_number == 0:
        return True
    return db.scalar(
        select(
            exists().where(
                Email.campaign_id == email.campaign_id,
                Email.contact_id == email.contact_id,
                Email.sequence_number == email.sequence_number - 1,
                Email.status.in_(SENT_LIKE_STATUSES),
            )
        )
    )


def can_send(db: Session, email: Email) -> SendDecision:
    contact = db.get(Contact, email.contact_id)
    campaign = db.get(Campaign, email.campaign_id)
    lead = db.get(Lead, email.lead_id)
    reasons: list[str] = []

    # --- the person ---
    if contact.suppressed:
        reasons.append("contact_suppressed")
    if contact.unsubscribed:
        reasons.append("contact_unsubscribed")
    if is_suppressed(db, contact.organization_id, contact.email_hash):
        reasons.append("suppression_record_exists")
    if not contact.email:
        reasons.append("missing_recipient_address")
    if contact_has_replied(db, contact.id, campaign.id):
        reasons.append("recipient_replied")

    # --- the campaign / lead ---
    if campaign.status == CampaignStatus.PAUSED:
        reasons.append("campaign_paused")
    elif campaign.status != CampaignStatus.ACTIVE:
        reasons.append("campaign_not_active")
    if lead.disabled:
        reasons.append("lead_disabled")

    # --- the email itself ---
    if email.status in SENT_LIKE_STATUSES:
        reasons.append("already_sent")
    elif email.status not in (EmailStatus.APPROVED, EmailStatus.SCHEDULED, EmailStatus.FAILED):
        reasons.append("not_approved")
    if email.approved_at is None and "not_approved" not in reasons:
        reasons.append("not_approved")
    if followup_limit_reached(email, campaign):
        reasons.append("followup_limit_reached")
    if not previous_step_sent(db, email):
        reasons.append("previous_step_not_sent")
    if duplicate_email_exists(db, email, contact):
        reasons.append("duplicate_email")

    return SendDecision(allowed=not reasons, reasons=reasons)
