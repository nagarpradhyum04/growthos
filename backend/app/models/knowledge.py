import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, Timestamps, UUIDPk


class KnowledgeDocument(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "knowledge_documents"

    # NULL product = applies to the whole business (policies, general FAQ).
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"),
                                                         index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # manual | faq | warranty_policy | service | policy
    doc_type: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class KnowledgeChunk(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "knowledge_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
                                                   index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(index=True, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
