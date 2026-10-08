from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, Timestamps, UUIDPk


class SuppressionRecord(UUIDPk, Timestamps, OrgScoped, Base):
    """Minimal record that keeps a person suppressed even after their profile data is erased.

    Stores only a SHA-256 hash of the normalized email address — never the address itself.
    Every send and every new contact is checked against this table.
    """

    __tablename__ = "suppression_records"
    __table_args__ = (UniqueConstraint("organization_id", "email_hash", name="uq_suppression_org_email"),)

    email_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="", nullable=False)
