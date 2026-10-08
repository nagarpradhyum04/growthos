import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, Timestamps, UUIDPk, str_enum
from app.models.enums import EmailStatus, FollowupStatus, PriorityTier, ReplyClassification


class EmailDraft(UUIDPk, Timestamps, OrgScoped, Base):
    """Immutable record of what an agent generated. The sendable, human-edited copy lives in `emails`."""

    __tablename__ = "email_drafts"

    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    personalization_used: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class Email(UUIDPk, Timestamps, OrgScoped, Base):
    """One step of the outreach sequence for a contact in a campaign.

    The unique constraint on (campaign, contact, sequence_number) is the database-level
    guarantee against duplicate sends for the same step.
    """

    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id", "sequence_number", name="uq_email_sequence_step"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="SET NULL"), nullable=True
    )
    # 0 = initial email, 1..N = follow-ups
    sequence_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EmailStatus] = mapped_column(
        str_enum(EmailStatus), default=EmailStatus.DRAFT, index=True, nullable=False
    )
    edited_by_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    send_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class EmailReply(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "email_replies"

    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"), index=True, nullable=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    # Provider message id for idempotent ingestion of webhook retries.
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    subject: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Filled by the Reply Analysis Agent.
    classification: Mapped[ReplyClassification | None] = mapped_column(
        str_enum(ReplyClassification), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_human_attention: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Email Intelligence: tier is decided by backend rules from detected intents (services/escalation.py).
    tier: Mapped[PriorityTier | None] = mapped_column(str_enum(PriorityTier), nullable=True)
    intents: Mapped[list] = mapped_column(JSON, default=list, server_default="[]", nullable=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # True when the backend's deterministic opt-out detector fired (independent of the LLM).
    opt_out_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )


class Followup(UUIDPk, Timestamps, OrgScoped, Base):
    """A scheduled follow-up step. Created when the previous step is sent."""

    __tablename__ = "followups"
    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id", "sequence_number", name="uq_followup_step"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    previous_email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"), nullable=True
    )
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"), nullable=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    status: Mapped[FollowupStatus] = mapped_column(
        str_enum(FollowupStatus), default=FollowupStatus.PENDING, index=True, nullable=False
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
