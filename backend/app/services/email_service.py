"""Email review, approval and sending. Every send goes through can_send()."""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ExternalServiceError, InvalidStateError, SendBlockedError
from app.models import Campaign, Contact, Email, Followup, Lead, Organization
from app.models.enums import EmailStatus, FollowupStatus, LeadStatus
from app.security import create_unsubscribe_token
from app.services.container import Container
from app.services.email import EmailSendError, OutgoingEmail
from app.services.safety import can_send, followup_delay_days_for

logger = logging.getLogger(__name__)

EDITABLE_STATUSES = {EmailStatus.DRAFT, EmailStatus.APPROVED, EmailStatus.FAILED}


def update_email_content(email: Email, subject: str, body: str) -> Email:
    if email.status not in EDITABLE_STATUSES:
        raise InvalidStateError(f"An email in status {email.status} cannot be edited.")
    if not subject.strip() or not body.strip():
        raise InvalidStateError("Subject and body cannot be empty.")
    if subject != email.subject or body != email.body:
        email.subject = subject.strip()
        email.body = body.strip()
        email.edited_by_human = True
        # Any edit after approval requires a fresh approval.
        email.status = EmailStatus.DRAFT
        email.approved_at = None
        email.approved_by_user_id = None
    return email


def approve_email(email: Email, user_id: uuid.UUID | None) -> Email:
    if email.status not in (EmailStatus.DRAFT, EmailStatus.APPROVED, EmailStatus.FAILED):
        raise InvalidStateError(f"An email in status {email.status} cannot be approved.")
    email.status = EmailStatus.APPROVED
    email.approved_at = datetime.now(timezone.utc)
    email.approved_by_user_id = user_id
    return email


def reject_email(db: Session, email: Email) -> None:
    """Discard an unsent draft so a new one can be generated. Never touches sent emails."""
    if email.status not in EDITABLE_STATUSES:
        raise InvalidStateError(f"An email in status {email.status} cannot be rejected.")
    lead = db.get(Lead, email.lead_id)
    if email.sequence_number == 0 and lead.status == LeadStatus.DRAFTED:
        lead.status = LeadStatus.QUALIFIED
    lead.last_activity_at = datetime.now(timezone.utc)
    db.execute(
        Followup.__table__.update().where(Followup.email_id == email.id)
        .values(status=FollowupStatus.CANCELLED, cancel_reason="draft_rejected_by_reviewer")
    )
    db.delete(email)
    db.flush()


def unsubscribe_footer(contact: Contact) -> str:
    token = create_unsubscribe_token(contact.id, contact.organization_id)
    url = f"{get_settings().public_base_url.rstrip('/')}/public/unsubscribe?token={token}"
    return f"\n\n--\nDon't want to hear from us? Unsubscribe: {url}"


def send_email(db: Session, email_id: uuid.UUID, organization_id: uuid.UUID, container: Container) -> Email:
    """Send one email. Row-locked so concurrent/duplicate requests cannot double-send.

    Commits its own transaction so the outcome (SENT / FAILED / SUPPRESSED) is durable.
    """
    email = db.scalar(
        select(Email).where(Email.id == email_id, Email.organization_id == organization_id).with_for_update()
    )
    if email is None:
        from app.errors import NotFoundError

        raise NotFoundError("Email not found")

    decision = can_send(db, email)
    if not decision.allowed:
        if decision.suppressed and email.status not in (EmailStatus.SENT, EmailStatus.DELIVERED,
                                                        EmailStatus.REPLIED, EmailStatus.COMPLETED):
            email.status = EmailStatus.SUPPRESSED
        db.commit()
        raise SendBlockedError("This email cannot be sent.", details={"reasons": decision.reasons})

    contact = db.get(Contact, email.contact_id)
    org = db.get(Organization, email.organization_id)
    settings = container.settings
    email.send_attempts += 1
    try:
        result = container.email_provider.send(
            OutgoingEmail(
                to=contact.email,
                subject=email.subject,
                body=email.body + unsubscribe_footer(contact),
                from_address=settings.email_from_address or f"{org.name} <no-reply@example.com>",
                idempotency_key=str(email.id),
            )
        )
    except EmailSendError as exc:
        email.status = EmailStatus.FAILED
        email.last_error = str(exc)
        db.commit()
        logger.warning("Email %s failed to send: %s", email.id, exc)
        raise ExternalServiceError("The email provider failed to send this email. You can retry.") from exc

    now = datetime.now(timezone.utc)
    email.status = EmailStatus.SENT
    email.sent_at = now
    email.last_error = None
    email.provider_message_id = result.provider_message_id
    lead = db.get(Lead, email.lead_id)
    if lead.status not in (LeadStatus.SUPPRESSED, LeadStatus.REPLIED):
        lead.status = LeadStatus.CONTACTED
    lead.last_activity_at = now
    _schedule_next_followup(db, email, now)
    db.commit()
    return email


def _schedule_next_followup(db: Session, email: Email, sent_at: datetime) -> None:
    """Create the next follow-up step. Steps beyond the limit are still created so the worker can
    close the sequence (LIMIT_REACHED) once the wait is over without a reply."""
    campaign = db.get(Campaign, email.campaign_id)
    exists = db.scalar(
        select(Followup.id).where(Followup.campaign_id == email.campaign_id, Followup.contact_id == email.contact_id,
                                  Followup.sequence_number == email.sequence_number + 1)
    )
    if exists:
        return
    db.add(Followup(organization_id=email.organization_id, campaign_id=email.campaign_id, lead_id=email.lead_id,
                    contact_id=email.contact_id, previous_email_id=email.id,
                    sequence_number=email.sequence_number + 1,
                    due_at=sent_at + timedelta(days=followup_delay_days_for(campaign)),
                    status=FollowupStatus.PENDING))


def mark_delivered(db: Session, provider_message_id: str) -> Email | None:
    email = db.scalar(select(Email).where(Email.provider_message_id == provider_message_id))
    if email and email.status == EmailStatus.SENT:
        email.status = EmailStatus.DELIVERED
        email.delivered_at = datetime.now(timezone.utc)
    return email
