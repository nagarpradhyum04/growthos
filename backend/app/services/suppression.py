"""Suppression, unsubscribe and Forget Me enforcement.

Design: a person's suppression is stored as a SHA-256 hash of their normalized email address in
suppression_records. Profile data can be erased (Forget Me) without ever making the person
contactable again, because every new contact and every send is checked against that hash.
"""
import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    AgentRun,
    Contact,
    Email,
    EmailDraft,
    EmailReply,
    Followup,
    Job,
    Lead,
    ResearchResult,
    SuppressionRecord,
)
from app.models.enums import (
    EmailStatus,
    FollowupStatus,
    JobStatus,
    LeadStatus,
    SuppressionReason,
    UNSENT_STATUSES,
)

ERASED = "[erased: Forget Me request]"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_email(email: str) -> str:
    return hashlib.sha256(normalize_email(email).encode()).hexdigest()


def is_suppressed(db: Session, organization_id: uuid.UUID, email_hash: str) -> bool:
    return (
        db.scalar(
            select(SuppressionRecord.id).where(
                SuppressionRecord.organization_id == organization_id,
                SuppressionRecord.email_hash == email_hash,
            )
        )
        is not None
    )


def _upsert_record(db: Session, contact: Contact, reason: SuppressionReason, source: str) -> None:
    record = db.scalar(
        select(SuppressionRecord).where(
            SuppressionRecord.organization_id == contact.organization_id,
            SuppressionRecord.email_hash == contact.email_hash,
        )
    )
    if record is None:
        db.add(SuppressionRecord(organization_id=contact.organization_id, email_hash=contact.email_hash,
                                 reason=reason.value, source=source))
    elif reason == SuppressionReason.FORGET_ME:
        record.reason = reason.value  # Forget Me is the strongest reason; keep it.
        record.source = source


def cancel_pending_followups(db: Session, contact_id: uuid.UUID, reason: str) -> int:
    result = db.execute(
        update(Followup)
        .where(Followup.contact_id == contact_id, Followup.status == FollowupStatus.PENDING)
        .values(status=FollowupStatus.CANCELLED, cancel_reason=reason)
    )
    return result.rowcount or 0


def _block_unsent_emails(db: Session, contact_id: uuid.UUID) -> None:
    db.execute(
        update(Email)
        .where(Email.contact_id == contact_id, Email.status.in_(UNSENT_STATUSES))
        .values(status=EmailStatus.SUPPRESSED)
    )


def _cancel_jobs_for(db: Session, lead_id: uuid.UUID, contact_id: uuid.UUID) -> None:
    jobs = db.scalars(select(Job).where(Job.status == JobStatus.QUEUED)).all()
    for job in jobs:
        if job.payload.get("lead_id") == str(lead_id) or job.payload.get("contact_id") == str(contact_id):
            job.status = JobStatus.CANCELLED
            job.last_error = "Cancelled: contact suppressed"


def _refresh_lead_status(db: Session, lead: Lead) -> None:
    contacts = db.scalars(select(Contact).where(Contact.lead_id == lead.id)).all()
    if contacts and all(c.suppressed for c in contacts):
        lead.status = LeadStatus.SUPPRESSED
    lead.last_activity_at = datetime.now(timezone.utc)


def suppress_contact(db: Session, contact: Contact, reason: SuppressionReason, source: str) -> None:
    """Unsubscribe / manual suppression: stop all outreach, keep the data."""
    _upsert_record(db, contact, reason, source)
    contact.suppressed = True
    contact.suppression_reason = reason.value
    if reason in (SuppressionReason.UNSUBSCRIBED, SuppressionReason.FORGET_ME):
        contact.unsubscribed = True
    cancel_pending_followups(db, contact.id, f"suppressed:{reason.value}")
    _block_unsent_emails(db, contact.id)
    _cancel_jobs_for(db, contact.lead_id, contact.id)
    lead = db.get(Lead, contact.lead_id)
    _refresh_lead_status(db, lead)
    from app.services import approval_service
    from app.services import workflow_service as wfs
    from app.models.enums import ApprovalStatus, TraceStatus, WorkflowState

    approval_service.resolve_for(db, status=ApprovalStatus.CANCELLED, note=f"Contact suppressed ({reason.value})",
                                 lead_id=lead.id)
    wfs.advance_lead(db, lead, "safety", "Suppress contact", TraceStatus.BLOCKED,
                     f"Contact suppressed ({reason.value.replace('_', ' ')}): pending follow-ups cancelled, "
                     "unsent emails blocked, future outreach impossible", state=WorkflowState.BLOCKED)
    db.flush()


def forget_contact(db: Session, contact: Contact, source: str) -> None:
    """Forget Me: suppress forever, then erase everything personal except the suppression hash."""
    suppress_contact(db, contact, SuppressionReason.FORGET_ME, source)
    now = datetime.now(timezone.utc)
    contact.name = None
    contact.role = None
    contact.email = None
    contact.forgotten_at = now
    db.flush()

    db.execute(update(Email).where(Email.contact_id == contact.id).values(subject=ERASED, body=ERASED))
    db.execute(update(EmailDraft).where(EmailDraft.contact_id == contact.id)
               .values(subject=ERASED, body=ERASED, personalization_used=[]))
    db.execute(update(EmailReply).where(EmailReply.contact_id == contact.id)
               .values(subject=ERASED, body=ERASED, summary=ERASED, external_id=None))

    lead = db.get(Lead, contact.lead_id)
    remaining = db.scalars(
        select(Contact).where(Contact.lead_id == lead.id, Contact.forgotten_at.is_(None))
    ).all()
    if not remaining:
        # Research and agent logs can mention the person; with no other contacts there is no
        # reason to keep them.
        db.execute(update(AgentRun).where(AgentRun.lead_id == lead.id).values(input=None, output=None))
        for research in db.scalars(select(ResearchResult).where(ResearchResult.lead_id == lead.id)):
            db.delete(research)
        lead.notes = ""
        from app.models import Approval
        from app.services.memory_service import forget_subject

        forget_subject(db, lead.organization_id, lead.id)
        db.execute(update(Approval).where(Approval.lead_id == lead.id)
                   .values(suggested_response="", status="CANCELLED"))
    db.flush()
