import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, Timestamps, UUIDPk, str_enum
from app.models.enums import (
    CustomerStatus,
    MessageSender,
    PriorityTier,
    PurchaseStatus,
    ServiceStatus,
    WarrantyStatus,
)


class Customer(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("organization_id", "email_hash", name="uq_customer_org_email"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    company: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    status: Mapped[CustomerStatus] = mapped_column(str_enum(CustomerStatus), default=CustomerStatus.ACTIVE,
                                                   nullable=False)
    # Converted from this lead/contact (if acquired through GrowthOS outreach).
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"),
                                                         nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # {"lifecycle_messages": bool}
    preferences: Mapped[dict] = mapped_column(JSON, default=lambda: {"lifecycle_messages": True}, nullable=False)


class Product(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    warranty_months: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Purchase(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "purchases"

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    purchased_at: Mapped[date] = mapped_column(Date, nullable=False)
    warranty_expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    serial_number: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    order_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[PurchaseStatus] = mapped_column(str_enum(PurchaseStatus), default=PurchaseStatus.ACTIVE,
                                                   nullable=False)


class WarrantyClaim(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "warranty_claims"

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    purchase_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchases.id", ondelete="CASCADE"), index=True)
    issue: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[WarrantyStatus] = mapped_column(str_enum(WarrantyStatus), default=WarrantyStatus.SUBMITTED,
                                                   index=True, nullable=False)
    # Deterministic eligibility check + retrieved policy excerpts; advisory only.
    eligibility: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # visible to the customer
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                                 nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ServiceRequest(UUIDPk, Timestamps, OrgScoped, Base):
    """A repair/service request. Once CONFIRMED with `scheduled_for`, it is the customer's appointment."""

    __tablename__ = "service_requests"

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    purchase_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchases.id", ondelete="CASCADE"), index=True)
    issue: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    preferred_time: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    contact_email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    status: Mapped[ServiceStatus] = mapped_column(str_enum(ServiceStatus),
                                                  default=ServiceStatus.PENDING_CONFIRMATION, index=True,
                                                  nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # visible to the customer
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Conversation(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "conversations"

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    # "business" (customer <-> business inbox) | "support_ai" (Product Support AI chat)
    channel: Mapped[str] = mapped_column(String(32), default="business", nullable=False)
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchases.id", ondelete="SET NULL"),
                                                          nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Message(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"),
                                                       index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    sender: Mapped[MessageSender] = mapped_column(str_enum(MessageSender), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Email Intelligence results (internal; never shown to the customer).
    tier: Mapped[PriorityTier | None] = mapped_column(str_enum(PriorityTier), nullable=True)
    intents: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # For AI answers: the knowledge sources used.
    sources: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    handled_automatically: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Notification(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "notifications"

    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"),
                                                          index=True, nullable=True)  # NULL = business owner
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    link: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LifecycleEvent(UUIDPk, Timestamps, OrgScoped, Base):
    """Idempotency + audit for lifecycle follow-ups (one row per event per purchase/service)."""

    __tablename__ = "lifecycle_events"

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # SENT | SKIPPED | BLOCKED
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"),
                                                         nullable=True)
