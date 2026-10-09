import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, Timestamps, UUIDPk


class SocialPost(UUIDPk, Timestamps, OrgScoped, Base):
    """One weekly promotional post for the business's social page: kind 'image' (static) or 'video'.

    Text is written by the Social Content Agent; media by the configured media provider (Nano Banana for
    images, Veo for video). Nothing is published automatically: a human approves, then posts it.
    """

    __tablename__ = "social_posts"
    __table_args__ = (UniqueConstraint("organization_id", "week_start", "kind", name="uq_social_week_kind"),)

    week_start: Mapped[date] = mapped_column(Date, index=True, nullable=False)  # Monday of the week
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # image | video
    # GENERATING | READY | NEEDS_REVIEW (policy flagged) | FAILED | APPROVED | REJECTED
    status: Mapped[str] = mapped_column(String(16), default="GENERATING", nullable=False)
    theme: Mapped[str] = mapped_column(Text, default="", nullable=False)
    headline: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    caption: Mapped[str] = mapped_column(Text, default="", nullable=False)
    hashtags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    platforms: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    media_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    media_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    media_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    media_provider: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    media_model: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    policy_notes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"),
                                                           nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                                  nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
