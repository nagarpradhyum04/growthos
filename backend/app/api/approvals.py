"""Pending human actions: approve / reject / take over / mark as automated."""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, container, current_user
from app.db import get_db
from app.errors import InvalidStateError
from app.models import (Approval, Customer, Email, EmailReply, Lead, Message, ServiceRequest, SocialPost,
                        WarrantyClaim)
from app.models.enums import ApprovalStatus, ApprovalType, ServiceStatus, WarrantyStatus
from app.services import approval_service, customer_care, email_service, social_service
from app.services.common import get_owned
from app.services.container import Container
from app.services.escalation import RED
from app.services.policy import get_or_create_policy

router = APIRouter(prefix="/approvals", tags=["approvals"])


class Decision(BaseModel):
    note: str = Field(default="", max_length=2000)
    response: str = Field(default="", max_length=5000)  # reply text to send to a customer (message escalations)
    send: bool = True  # outbound email: approve AND send


def approval_dict(db: Session, a: Approval) -> dict:
    subject = {}
    if a.email_id and (e := db.get(Email, a.email_id)):
        subject = {"kind": "email", "id": str(e.id), "subject": e.subject, "body": e.body, "status": e.status.value}
    elif a.reply_id and (r := db.get(EmailReply, a.reply_id)):
        subject = {"kind": "reply", "id": str(r.id), "body": r.body, "classification": r.classification.value if r.classification else None,
                   "intents": r.intents}
    elif a.message_id and (m := db.get(Message, a.message_id)):
        subject = {"kind": "message", "id": str(m.id), "body": m.body, "intents": m.intents}
    elif a.warranty_claim_id and (w := db.get(WarrantyClaim, a.warranty_claim_id)):
        subject = {"kind": "warranty_claim", "id": str(w.id), "issue": w.issue, "status": w.status.value,
                   "eligibility": w.eligibility}
    elif a.service_request_id and (s := db.get(ServiceRequest, a.service_request_id)):
        subject = {"kind": "service_request", "id": str(s.id), "issue": s.issue, "status": s.status.value,
                   "preferred_date": s.preferred_date, "preferred_time": s.preferred_time}
    elif a.social_post_id and (sp := db.get(SocialPost, a.social_post_id)):
        subject = {"kind": "social_post", "id": str(sp.id), "post_kind": sp.kind, "status": sp.status,
                   "theme": sp.theme, "caption": sp.caption, "hashtags": sp.hashtags, "policy_notes": sp.policy_notes,
                   "has_media": bool(sp.media_path), "is_mock_media": sp.media_provider == "mock"}
    lead = db.get(Lead, a.lead_id) if a.lead_id else None
    customer = db.get(Customer, a.customer_id) if a.customer_id else None
    return {"id": str(a.id), "type": a.approval_type.value, "status": a.status.value, "priority": a.priority.value,
            "tier": a.tier.value if a.tier else None, "category": a.category, "title": a.title, "reason": a.reason,
            "recommended_action": a.recommended_action, "suggested_response": a.suggested_response,
            "lead_id": str(a.lead_id) if a.lead_id else None, "company_name": lead.company_name if lead else None,
            "customer_id": str(a.customer_id) if a.customer_id else None,
            "customer_name": customer.name if customer else None, "workflow_id": str(a.workflow_id) if a.workflow_id else None,
            "can_automate": bool(a.category) and a.category not in RED and a.approval_type in (
                ApprovalType.REPLY_ESCALATION, ApprovalType.MESSAGE_ESCALATION),
            "subject": subject, "created_at": a.created_at, "resolved_at": a.resolved_at,
            "resolution_note": a.resolution_note}


@router.get("")
def list_approvals(status: ApprovalStatus | None = ApprovalStatus.PENDING, cu: CurrentUser = Depends(current_user),
                   db: Session = Depends(get_db)):
    stmt = select(Approval).where(Approval.organization_id == cu.org_id)
    if status:
        stmt = stmt.where(Approval.status == status)
    order = {"URGENT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    items = sorted(db.scalars(stmt.order_by(Approval.created_at.desc()).limit(200)).all(),
                   key=lambda a: order[a.priority.value])
    return [approval_dict(db, a) for a in items]


def _pending(db: Session, approval_id: uuid.UUID, cu: CurrentUser) -> Approval:
    a = get_owned(db, Approval, approval_id, cu.org_id, for_update=True)
    if a.status != ApprovalStatus.PENDING:
        raise InvalidStateError(f"This item is already {a.status.value.lower()}.")
    return a


@router.post("/{approval_id}/approve")
def approve(approval_id: uuid.UUID, body: Decision, cu: CurrentUser = Depends(current_user),
            db: Session = Depends(get_db), c: Container = Depends(container)):
    """Approve = do the recommended action through the normal (safety-checked) code path."""
    a = _pending(db, approval_id, cu)
    if a.approval_type == ApprovalType.OUTBOUND_EMAIL:
        email = get_owned(db, Email, a.email_id, cu.org_id, for_update=True)
        email_service.approve_email(email, cu.id, db)
        db.commit()
        if body.send:
            email_service.send_email(db, email.id, cu.org_id, c)  # can_send() still decides
    elif a.approval_type == ApprovalType.MESSAGE_ESCALATION:
        text = body.response.strip() or a.suggested_response.strip()
        if not text:
            raise InvalidStateError("Write a response to send to the customer.")
        customer_care.business_reply(db, db.get(Customer, a.customer_id), text, cu.id)
        approval_service.resolve(a, ApprovalStatus.APPROVED, cu.id, body.note or "Response sent to customer")
    elif a.approval_type == ApprovalType.WARRANTY_CLAIM:
        customer_care.decide_warranty(db, db.get(WarrantyClaim, a.warranty_claim_id), WarrantyStatus.APPROVED,
                                      body.note, cu.id)
    elif a.approval_type == ApprovalType.SOCIAL_POST:
        social_service.decide(db, get_owned(db, SocialPost, a.social_post_id, cu.org_id), approve=True,
                              user_id=cu.id, note=body.note or "Approved for publishing")
    elif a.approval_type == ApprovalType.SERVICE_REQUEST:
        raise InvalidStateError("Confirm service requests with an appointment time on the Warranty & Service page.")
    else:  # REPLY_ESCALATION: the owner handled the opportunity
        approval_service.resolve(a, ApprovalStatus.APPROVED, cu.id, body.note or "Handled by owner")
    db.commit()
    db.refresh(a)
    return approval_dict(db, a)


@router.post("/{approval_id}/reject")
def reject(approval_id: uuid.UUID, body: Decision, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    a = _pending(db, approval_id, cu)
    if a.approval_type == ApprovalType.OUTBOUND_EMAIL:
        email_service.reject_email(db, get_owned(db, Email, a.email_id, cu.org_id, for_update=True))
    elif a.approval_type == ApprovalType.WARRANTY_CLAIM:
        if not body.note.strip():
            raise InvalidStateError("Explain the decision to the customer in the note.")
        customer_care.decide_warranty(db, db.get(WarrantyClaim, a.warranty_claim_id), WarrantyStatus.REJECTED,
                                      body.note, cu.id)
    elif a.approval_type == ApprovalType.SERVICE_REQUEST:
        customer_care.update_service(db, db.get(ServiceRequest, a.service_request_id), ServiceStatus.CANCELLED,
                                     note=body.note or "Request declined", user_id=cu.id)
    elif a.approval_type == ApprovalType.SOCIAL_POST and (sp := db.get(SocialPost, a.social_post_id)):
        if sp.status not in social_service.FINAL:
            social_service.decide(db, sp, approve=False, user_id=cu.id, note=body.note or "Rejected")
    approval_service.resolve(a, ApprovalStatus.REJECTED, cu.id, body.note or "Rejected")
    db.commit()
    return approval_dict(db, a)


@router.post("/{approval_id}/take-over")
def take_over(approval_id: uuid.UUID, body: Decision, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """The owner handles it personally; automation stays out of this conversation."""
    a = _pending(db, approval_id, cu)
    approval_service.resolve(a, ApprovalStatus.TAKEN_OVER, cu.id, body.note or "Owner took over")
    db.commit()
    return approval_dict(db, a)


@router.post("/{approval_id}/mark-automated")
def mark_automated(approval_id: uuid.UUID, body: Decision, cu: CurrentUser = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Resolve and let this category be automated from now on. RED categories can never be automated."""
    a = _pending(db, approval_id, cu)
    if not a.category or a.category in RED or a.approval_type not in (ApprovalType.REPLY_ESCALATION,
                                                                    ApprovalType.MESSAGE_ESCALATION):
        raise InvalidStateError("This kind of decision must always be made by a human.")
    policy = get_or_create_policy(db, cu.org_id)
    policy.escalation_rules = {**policy.escalation_rules, a.category: "automate"}
    approval_service.resolve(a, ApprovalStatus.AUTOMATED, cu.id, body.note or f"Future '{a.category}' messages automated")
    db.commit()
    return approval_dict(db, a)
