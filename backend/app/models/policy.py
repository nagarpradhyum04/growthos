import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk

DEFAULT_BANNED_PHRASES = [
    "guaranteed results", "risk-free", "act now", "100% free", "limited time offer", "click here",
]

# Escalation categories the owner may switch between "escalate" and "automate".
# RED categories are locked to "escalate" by services/escalation.py regardless of this setting.
DEFAULT_ESCALATION_RULES = {
    "purchase_intent": "escalate",
    "large_order": "escalate",
    "pricing_inquiry": "escalate",
    "discount_request": "escalate",
    "meeting_request": "escalate",
    "routine_question": "automate",
    "greeting": "automate",
    "brochure_request": "automate",
}

DEFAULT_LIFECYCLE_RULES = {
    "setup_help_days": 3,
    "post_purchase_checkin_days": 7,
    "warranty_expiry_notice_days": 30,
    "post_service_days": 2,
}


class BusinessPolicy(UUIDPk, Timestamps, Base):
    """Owner-configurable automation & safety rules, enforced by the backend (never by the LLM)."""

    __tablename__ = "business_policies"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False)
    # Outbound frequency limits (across all campaigns, per person).
    max_messages_per_contact_30d: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    min_hours_between_messages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_domains: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    banned_phrases: Mapped[list] = mapped_column(JSON, default=lambda: list(DEFAULT_BANNED_PHRASES), nullable=False)
    escalation_rules: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_ESCALATION_RULES),
                                                   nullable=False)
    large_order_threshold: Mapped[float] = mapped_column(Numeric(12, 2), default=10000, nullable=False)
    auto_handle_routine: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    warranty_auto_approve: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lifecycle_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    lifecycle_rules: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_LIFECYCLE_RULES),
                                                  nullable=False)
    lifecycle_max_per_7d: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Weekly social promotion: 1 static + 1 video post drafted every week (never auto-published).
    social_weekly_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    social_platforms: Mapped[list] = mapped_column(JSON, default=lambda: ["instagram", "linkedin", "facebook"],
                                                   server_default='["instagram", "linkedin", "facebook"]', nullable=False)
