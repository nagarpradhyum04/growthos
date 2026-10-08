import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, Timestamps, UUIDPk, str_enum
from app.models.enums import TraceStatus, WorkflowState, WorkflowType


class Workflow(UUIDPk, Timestamps, OrgScoped, Base):
    """A unit of orchestrated work and its state machine (see services/orchestrator.py)."""

    __tablename__ = "workflows"

    workflow_type: Mapped[WorkflowType] = mapped_column(str_enum(WorkflowType), index=True, nullable=False)
    goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    state: Mapped[WorkflowState] = mapped_column(str_enum(WorkflowState), default=WorkflowState.PENDING,
                                                 index=True, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"),
                                                        index=True, nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), index=True,
                                                      nullable=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"),
                                                          nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"),
                                                          index=True, nullable=True)
    # The orchestrator's plan (ordered steps) and a running summary (counts / outcome).
    plan: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowEvent(UUIDPk, Timestamps, OrgScoped, Base):
    """Agent trace: one row per important step taken inside a workflow."""

    __tablename__ = "workflow_events"

    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    # orchestrator | research | qualification | outreach | safety | human | email_intelligence | followup |
    # analytics | memory | support | warranty | service | lifecycle | system
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[TraceStatus] = mapped_column(str_enum(TraceStatus), nullable=False)
    result: Mapped[str] = mapped_column(Text, default="", nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    state_after: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"),
                                                           nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
