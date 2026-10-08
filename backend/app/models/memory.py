import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, Timestamps, UUIDPk


class MemoryEntry(UUIDPk, Timestamps, OrgScoped, Base):
    """Shared memory: structured facts any agent can write and read.

    Relational data (emails, replies, purchases...) stays in its own tables; memory holds the distilled
    context that agents pass to each other (research facts, preferences, intents, learned insights).
    """

    __tablename__ = "memory_entries"

    # business | lead | customer | campaign | product
    scope: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(index=True, nullable=True)
    # customer_info | preference | product | campaign | conversation | result | research | insight
    category: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)  # agent name or "user"
    importance: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflows.id", ondelete="SET NULL"),
                                                          nullable=True)
