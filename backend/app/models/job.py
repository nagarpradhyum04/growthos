import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk, str_enum, utcnow
from app.models.enums import JobStatus


class Job(UUIDPk, Timestamps, Base):
    """A unit of background work. The worker claims rows with SELECT ... FOR UPDATE SKIP LOCKED."""

    __tablename__ = "jobs"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Optional key to prevent the same job being queued twice while one is pending.
    dedupe_key: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    status: Mapped[JobStatus] = mapped_column(
        str_enum(JobStatus), default=JobStatus.QUEUED, index=True, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
