import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, OrgScoped, Timestamps, UUIDPk, str_enum, utcnow
from app.models.enums import LeadStatus


class Lead(UUIDPk, Timestamps, OrgScoped, Base):
    """A target company inside a campaign."""

    __tablename__ = "leads"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    website: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[LeadStatus] = mapped_column(
        str_enum(LeadStatus), default=LeadStatus.NEW, nullable=False
    )
    # Manually disabled leads never receive outreach.
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Latest qualification (history lives in agent_runs).
    qualified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    qualification_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qualification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_angle: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualification_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    contacts: Mapped[list["Contact"]] = relationship(back_populates="lead", order_by="Contact.created_at")
    research_results: Mapped[list["ResearchResult"]] = relationship(
        back_populates="lead", order_by="ResearchResult.created_at.desc()"
    )


class Contact(UUIDPk, Timestamps, OrgScoped, Base):
    """A person at a lead. Personal fields are erased on Forget Me; email_hash is kept for suppression."""

    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("lead_id", "email_hash", name="uq_contact_lead_email"),)

    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    suppressed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    suppression_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unsubscribed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    forgotten_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lead: Mapped[Lead] = relationship(back_populates="contacts")


class ResearchResult(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "research_results"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    # Validated ResearchOutput payload (company_summary, industry, ..., sources).
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    lead: Mapped[Lead] = relationship(back_populates="research_results")
