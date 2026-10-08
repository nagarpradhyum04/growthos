import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, container, current_user
from app.db import get_db
from app.models import Contact, EmailReply, Followup, Lead
from app.models.enums import FollowupStatus, ReplyClassification
from app.schemas import ReplyCreate, ReplyOut, ReplyWithContext
from app.services import jobs, reply_service
from app.services.common import get_owned
from app.services.container import Container

router = APIRouter(prefix="/replies", tags=["replies"])


def with_context(db: Session, reply: EmailReply) -> ReplyWithContext:
    contact = db.get(Contact, reply.contact_id)
    lead = db.get(Lead, reply.lead_id)

    def followups(status: FollowupStatus) -> int:
        return db.scalar(select(func.count(Followup.id)).where(
            Followup.contact_id == reply.contact_id, Followup.campaign_id == reply.campaign_id,
            Followup.status == status)) or 0

    return ReplyWithContext(
        **ReplyOut.model_validate(reply).model_dump(),
        company_name=lead.company_name,
        followups_cancelled=followups(FollowupStatus.CANCELLED),
        followups_pending=followups(FollowupStatus.PENDING),
        contact_suppressed=contact.suppressed,
        contact_forgotten=contact.forgotten_at is not None,
    )


@router.get("", response_model=list[ReplyWithContext])
def list_replies(classification: ReplyClassification | None = None, needs_attention: bool | None = None,
                 cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
                 limit: int = Query(200, le=500)):
    stmt = (select(EmailReply).where(EmailReply.organization_id == cu.org_id)
            .order_by(EmailReply.received_at.desc()).limit(limit))
    if classification:
        stmt = stmt.where(EmailReply.classification == classification)
    if needs_attention is not None:
        stmt = stmt.where(EmailReply.requires_human_attention.is_(needs_attention))
    return [with_context(db, r) for r in db.scalars(stmt).all()]


@router.post("", response_model=ReplyOut, status_code=201)
def record_reply(body: ReplyCreate, analyze_now: bool = False, cu: CurrentUser = Depends(current_user),
                 db: Session = Depends(get_db), c: Container = Depends(container)):
    """Manually log a reply (e.g. pasted from your inbox). Hard rules apply immediately;
    analysis is queued for the worker, or run inline with ?analyze_now=true."""
    reply, created = reply_service.record_reply(db, cu.org_id, email_id=body.email_id, subject=body.subject,
                                                body=body.body)
    db.commit()
    if created and reply.analyzed_at is None:
        if analyze_now:
            reply_service.analyze_reply(db, reply, c)
        else:
            jobs.enqueue(db, "analyze_reply", {"reply_id": str(reply.id), "lead_id": str(reply.lead_id),
                                               "contact_id": str(reply.contact_id)},
                         organization_id=cu.org_id, dedupe_key=f"analyze_reply:{reply.id}")
        db.commit()
    return reply


@router.post("/{reply_id}/analyze", response_model=ReplyWithContext)
def analyze(reply_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
            c: Container = Depends(container)):
    reply = reply_service.analyze_reply(db, get_owned(db, EmailReply, reply_id, cu.org_id), c)
    db.commit()
    return with_context(db, reply)
