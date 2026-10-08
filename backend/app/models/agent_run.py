import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, Timestamps, UUIDPk, str_enum
from app.models.enums import AgentRunStatus


class AgentRun(UUIDPk, Timestamps, OrgScoped, Base):
    """Observability log: one row per agent execution (including retries)."""

    __tablename__ = "agent_runs"

    agent_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), index=True, nullable=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), index=True, nullable=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(
        str_enum(AgentRunStatus), default=AgentRunStatus.RUNNING, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Redacted payloads (email addresses removed). NULL when payload logging is disabled or erased.
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
