import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )


class OrgScoped:
    """Every tenant-owned row carries organization_id so queries can always be scoped."""

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )


def str_enum(enum_cls: type[enum.Enum]) -> Enum:
    """Store enums as VARCHAR (with a CHECK constraint) instead of native PG enums: simpler migrations."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
