import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, container, current_user
from app.db import get_db
from app.errors import InvalidStateError
from app.models import Contact, Email, EmailDraft, Lead
from app.models.enums import EmailStatus
from app.schemas import EmailOut, EmailReviewOut, EmailUpdate, SendRequest
from app.services import email_service, jobs
from app.services.common import get_owned, latest_research
from app.services.container import Container
from app.services.safety import can_send, describe_checks

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("", response_model=list[EmailOut])
def list_emails(status: EmailStatus | None = None, campaign_id: uuid.UUID | None = None,
                lead_id: uuid.UUID | None = None, cu: CurrentUser = Depends(current_user),
                db: Session = Depends(get_db)):
    stmt = select(Email).where(Email.organization_id == cu.org_id).order_by(Email.updated_at.desc()).limit(500)
    if status:
        stmt = stmt.where(Email.status == status)
    if campaign_id:
        stmt = stmt.where(Email.campaign_id == campaign_id)
    if lead_id:
        stmt = stmt.where(Email.lead_id == lead_id)
    return db.scalars(stmt).all()


def _review(db: Session, email: Email) -> EmailReviewOut:
    lead = db.get(Lead, email.lead_id)
    contact = db.get(Contact, email.contact_id)
    draft = db.get(EmailDraft, email.draft_id) if email.draft_id else None
    research = latest_research(db, lead.id)
    decision = can_send(db, email)
    return EmailReviewOut(
        **EmailOut.model_validate(email).model_dump(),
        company_name=lead.company_name,
        contact_name=contact.name,
        contact_email=contact.email,
        personalization_used=draft.personalization_used if draft else [],
        draft_confidence=draft.confidence if draft else None,
        research=research.data if research else None,
        send_check={"allowed": decision.allowed, "reasons": decision.reasons, "checks": describe_checks(decision)},
    )


@router.get("/{email_id}", response_model=EmailReviewOut)
def get_email(email_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return _review(db, get_owned(db, Email, email_id, cu.org_id))


@router.put("/{email_id}", response_model=EmailReviewOut)
def update_email(email_id: uuid.UUID, body: EmailUpdate, cu: CurrentUser = Depends(current_user),
                 db: Session = Depends(get_db)):
    email = get_owned(db, Email, email_id, cu.org_id, for_update=True)
    email_service.update_email_content(email, body.subject, body.body)
    db.commit()
    return _review(db, email)


@router.post("/{email_id}/approve", response_model=EmailReviewOut)
def approve(email_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    email = get_owned(db, Email, email_id, cu.org_id, for_update=True)
    email_service.approve_email(email, cu.id, db)
    db.commit()
    return _review(db, email)


@router.post("/{email_id}/send", response_model=EmailReviewOut)
def send(email_id: uuid.UUID, body: SendRequest | None = Body(default=None),
         cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db), c: Container = Depends(container)):
    send_at = body.send_at if body else None
    if send_at and send_at > datetime.now(timezone.utc):
        email = get_owned(db, Email, email_id, cu.org_id, for_update=True)
        if email.status not in (EmailStatus.APPROVED, EmailStatus.SCHEDULED):
            raise InvalidStateError("Approve the email before scheduling it.")
        email.status = EmailStatus.SCHEDULED
        email.scheduled_for = send_at
        jobs.enqueue(db, "send_scheduled_email", {"email_id": str(email.id), "lead_id": str(email.lead_id),
                                                  "contact_id": str(email.contact_id)},
                     organization_id=cu.org_id, run_at=send_at, dedupe_key=f"send:{email.id}")
        db.commit()
        return _review(db, email)
    email = email_service.send_email(db, email_id, cu.org_id, c)
    return _review(db, email)


@router.post("/{email_id}/reject", response_model=EmailOut)
def reject(email_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Reviewer rejects an unsent AI draft. The agent's original output stays in email_drafts for audit."""
    email = get_owned(db, Email, email_id, cu.org_id, for_update=True)
    snapshot = EmailOut.model_validate(email)
    email_service.reject_email(db, email)
    db.commit()
    return snapshot
