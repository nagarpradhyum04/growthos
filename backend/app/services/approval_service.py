"""Human escalation inbox. Every approval explains WHY it exists (`reason`)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Approval, Notification
from app.models.enums import ApprovalStatus, ApprovalType, Priority


def create(db: Session, organization_id: uuid.UUID, approval_type: ApprovalType, *, title: str, reason: str,
           priority: Priority = Priority.MEDIUM, tier=None, category: str = "", recommended_action: str = "",
           suggested_response: str = "", notify: bool = True, **refs) -> Approval:
    """Create a pending approval, or refresh the existing pending one for the same subject."""
    stmt = select(Approval).where(Approval.organization_id == organization_id,
                                  Approval.approval_type == approval_type,
                                  Approval.status == ApprovalStatus.PENDING)
    for key in ("email_id", "reply_id", "message_id", "warranty_claim_id", "service_request_id"):
        if refs.get(key):
            stmt = stmt.where(getattr(Approval, key) == refs[key])
            break
    existing = db.scalar(stmt) if any(refs.get(k) for k in ("email_id", "reply_id", "message_id",
                                                            "warranty_claim_id", "service_request_id")) else None
    approval = existing or Approval(organization_id=organization_id, approval_type=approval_type)
    approval.title = title[:300]
    approval.reason = reason
    approval.priority = priority
    approval.tier = tier
    approval.category = category
    approval.recommended_action = recommended_action
    approval.suggested_response = suggested_response
    for key, value in refs.items():
        setattr(approval, key, value)
    if existing is None:
        db.add(approval)
        if notify:
            db.add(Notification(organization_id=organization_id, customer_id=None, kind="approval",
                                title=f"Needs your decision: {title}"[:300], body=reason, link="/approvals"))
    db.flush()
    return approval


def resolve(approval: Approval, status: ApprovalStatus, user_id=None, note: str | None = None) -> Approval:
    approval.status = status
    approval.resolved_at = datetime.now(timezone.utc)
    approval.resolved_by_user_id = user_id
    if note:
        approval.resolution_note = note
    return approval


def resolve_for(db: Session, *, status: ApprovalStatus, user_id=None, note: str | None = None, **refs) -> int:
    """Close pending approvals tied to a subject (e.g. the email was approved from the review screen)."""
    stmt = select(Approval).where(Approval.status == ApprovalStatus.PENDING)
    for key, value in refs.items():
        stmt = stmt.where(getattr(Approval, key) == value)
    items = db.scalars(stmt).all()
    for a in items:
        resolve(a, status, user_id, note)
    return len(items)
