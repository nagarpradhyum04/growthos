import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class PortalAccessRequest(UUIDPk, Timestamps, Base):
    """A customer's request to sign in to the portal (Business ID + email), checked by the Access Agent.

    Stores only a hash of the email and of the one-time code.
    """

    __tablename__ = "portal_access_requests"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"),
                                                              index=True, nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"),
                                                          nullable=True)
    business_code: Mapped[str] = mapped_column(String(20), nullable=False)
    email_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # VERIFIED (code sent) | REJECTED | USED | LOCKED
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
