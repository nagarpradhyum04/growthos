import secrets
import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, OrgScoped, Timestamps, UUIDPk


_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I to avoid typos


def new_business_code() -> str:
    return "GOS-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


class Organization(UUIDPk, Timestamps, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Public Business ID the owner shares with customers; required to sign in to the customer portal.
    business_code: Mapped[str] = mapped_column(String(20), unique=True, default=new_business_code, nullable=False)
    # Off by default: every email needs a human approval. When enabled, generated
    # follow-ups are approved and sent automatically (still through can_send()).
    automated_sending_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="organization")
    business_profile: Mapped["BusinessProfile | None"] = relationship(back_populates="organization")


class User(UUIDPk, Timestamps, OrgScoped, Base):
    """Owner accounts (email + password) and customer-portal accounts (one per customer record).

    The same email may be an owner of one business and a customer of several others, so email is unique
    only among owners; a portal account is unique per customer record.
    """

    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_owner_email", "email", unique=True, postgresql_where=text("role = 'owner'")),
        Index("uq_users_customer_id", "customer_id", unique=True, postgresql_where=text("customer_id IS NOT NULL")),
    )

    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    # "owner" (business user) or "customer" (portal user, bound to one customer record).
    role: Mapped[str] = mapped_column(String(16), default="owner", server_default="owner", nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"),
                                                          nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="users")


class BusinessProfile(UUIDPk, Timestamps, Base):
    """The organization's own business knowledge. Fed to agents instead of relying on LLM memory."""

    __tablename__ = "business_profiles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    company_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    company_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    products_services: Mapped[str] = mapped_column(Text, default="", nullable=False)
    target_customers: Mapped[str] = mapped_column(Text, default="", nullable=False)
    value_proposition: Mapped[str] = mapped_column(Text, default="", nullable=False)
    industries: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    target_company_sizes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    tone: Mapped[str] = mapped_column(String(200), default="friendly, professional", nullable=False)
    website: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    key_differentiators: Mapped[str] = mapped_column(Text, default="", nullable=False)
    campaign_goals: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sender_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="business_profile")
