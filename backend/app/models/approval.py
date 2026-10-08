import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, Timestamps, UUIDPk, str_enum
from app.models.enums import ApprovalStatus, ApprovalType, Priority, PriorityTier


class Approval(UUIDPk, Timestamps, OrgScoped, Base):
    """A decision escalated to a human. `reason` always explains WHY it was escalated."""

    __tablename__ = "approvals"

    approval_type: Mapped[ApprovalType] = mapped_column(str_enum(ApprovalType), index=True, nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(str_enum(ApprovalStatus), default=ApprovalStatus.PENDING,
                                                   index=True, nullable=False)
    priority: Mapped[Priority] = mapped_column(str_enum(Priority), default=Priority.MEDIUM, nullable=False)
    tier: Mapped[PriorityTier | None] = mapped_column(str_enum(PriorityTier), nullable=True)
    category: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    suggested_response: Mapped[str] = mapped_column(Text, default="", nullable=False)

    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"),
                                                          nullable=True)
    email_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("emails.id", ondelete="SET NULL"), index=True,
                                                       nullable=True)
    reply_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("email_replies.id", ondelete="CASCADE"),
                                                       nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"),
                                                         nullable=True)
    warranty_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("warranty_claims.id", ondelete="CASCADE"), nullable=True)
    service_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=True)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflows.id", ondelete="SET NULL"),
                                                          nullable=True)

    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                                  nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
