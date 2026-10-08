"""API request/response schemas (separate from ORM models and agent output schemas)."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import (
    CampaignStatus,
    EmailStatus,
    FollowupStatus,
    LeadStatus,
    ReplyClassification,
)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class RegisterRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=200)
    name: str = Field(default="", max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORM):
    id: uuid.UUID
    email: str
    name: str
    organization_id: uuid.UUID


class OrganizationOut(ORM):
    id: uuid.UUID
    name: str
    automated_sending_enabled: bool


class MeResponse(BaseModel):
    user: UserOut
    organization: OrganizationOut


class OrganizationSettingsUpdate(BaseModel):
    automated_sending_enabled: bool


# ---------- business profile ----------
class BusinessProfileIn(BaseModel):
    company_name: str = Field(default="", max_length=200)
    company_description: str = Field(default="", max_length=5000)
    products_services: str = Field(default="", max_length=5000)
    target_customers: str = Field(default="", max_length=5000)
    value_proposition: str = Field(default="", max_length=5000)
    industries: list[str] = Field(default_factory=list, max_length=30)
    target_company_sizes: list[str] = Field(default_factory=list, max_length=10)
    tone: str = Field(default="friendly, professional", max_length=200)
    website: str = Field(default="", max_length=500)
    key_differentiators: str = Field(default="", max_length=5000)
    campaign_goals: str = Field(default="", max_length=5000)
    sender_name: str = Field(default="", max_length=200)


class BusinessProfileOut(BusinessProfileIn, ORM):
    id: uuid.UUID
    updated_at: datetime


# ---------- campaigns ----------
class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(default="", max_length=5000)
    target_audience: str = Field(default="", max_length=5000)
    max_followups: int | None = Field(default=None, ge=0, le=10)
    followup_delay_days: int | None = Field(default=None, ge=0, le=60)


class CampaignOut(ORM):
    id: uuid.UUID
    name: str
    objective: str
    target_audience: str
    status: CampaignStatus
    max_followups: int | None
    followup_delay_days: int | None
    created_at: datetime


class CampaignSummary(CampaignOut):
    leads: int
    qualified_leads: int
    emails_sent: int
    replies: int
    effective_max_followups: int


# ---------- leads ----------
class LeadCreate(BaseModel):
    campaign_id: uuid.UUID
    company_name: str = Field(min_length=1, max_length=200)
    website: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=5000)
    contact_name: str = Field(default="", max_length=200)
    contact_role: str = Field(default="", max_length=200)
    contact_email: EmailStr


class ContactOut(ORM):
    id: uuid.UUID
    name: str | None
    role: str | None
    email: str | None
    suppressed: bool
    suppression_reason: str | None
    unsubscribed: bool
    forgotten_at: datetime | None


class LeadListItem(ORM):
    id: uuid.UUID
    campaign_id: uuid.UUID
    campaign_name: str
    company_name: str
    contact_name: str | None
    contact_email: str | None
    qualification_score: int | None
    qualified: bool | None
    status: LeadStatus
    disabled: bool
    last_activity_at: datetime


class ResearchOut(ORM):
    id: uuid.UUID
    data: dict[str, Any]
    confidence: float
    created_at: datetime


class EmailOut(ORM):
    id: uuid.UUID
    campaign_id: uuid.UUID
    lead_id: uuid.UUID
    contact_id: uuid.UUID
    sequence_number: int
    subject: str
    body: str
    status: EmailStatus
    edited_by_human: bool
    approved_at: datetime | None
    scheduled_for: datetime | None
    sent_at: datetime | None
    delivered_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ReplyOut(ORM):
    id: uuid.UUID
    email_id: uuid.UUID | None
    lead_id: uuid.UUID
    contact_id: uuid.UUID
    campaign_id: uuid.UUID
    subject: str
    body: str
    received_at: datetime
    classification: ReplyClassification | None
    summary: str | None
    recommended_action: str | None
    requires_human_attention: bool
    opt_out_detected: bool
    analyzed_at: datetime | None


class ReplyWithContext(ReplyOut):
    """A reply plus the backend state it caused, so the UI can explain what happened."""

    company_name: str
    followups_cancelled: int
    followups_pending: int
    contact_suppressed: bool
    contact_forgotten: bool


class FollowupOut(ORM):
    id: uuid.UUID
    sequence_number: int
    due_at: datetime
    status: FollowupStatus
    cancel_reason: str | None
    email_id: uuid.UUID | None


class TimelineEvent(BaseModel):
    at: datetime
    type: str
    description: str
    # Who acted: "agent" | "human" | "system" (deterministic backend rule) | "contact"
    actor: str = "system"


class LeadDetail(ORM):
    id: uuid.UUID
    campaign: CampaignOut
    company_name: str
    website: str
    notes: str
    status: LeadStatus
    disabled: bool
    qualified: bool | None
    qualification_score: int | None
    qualification_reason: str | None
    recommended_angle: str | None
    qualification_breakdown: dict | None
    last_activity_at: datetime
    created_at: datetime
    contacts: list[ContactOut]
    research: ResearchOut | None
    emails: list[EmailOut]
    replies: list[ReplyOut]
    followups: list[FollowupOut]
    timeline: list[TimelineEvent]


class QualificationOut(BaseModel):
    qualified: bool
    score: int
    reason: str
    recommended_angle: str
    breakdown: dict | None


# ---------- emails ----------
class EmailUpdate(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=10000)


class SendRequest(BaseModel):
    send_at: datetime | None = None  # future time => SCHEDULED, handled by the worker


class EmailReviewOut(EmailOut):
    company_name: str
    contact_name: str | None
    contact_email: str | None
    personalization_used: list[str]
    draft_confidence: float | None
    research: dict[str, Any] | None
    send_check: dict[str, Any]


# ---------- replies ----------
class ReplyCreate(BaseModel):
    email_id: uuid.UUID
    subject: str = Field(default="", max_length=1000)
    body: str = Field(min_length=1, max_length=50000)


class InboundEmailWebhook(BaseModel):
    """Provider-agnostic inbound email payload."""

    organization_id: uuid.UUID
    from_address: EmailStr
    subject: str = ""
    body: str
    message_id: str | None = None
    in_reply_to_email_id: uuid.UUID | None = None
    received_at: datetime | None = None


class DeliveryWebhook(BaseModel):
    provider_message_id: str
    event: str  # "delivered" | "bounced" | ...


class JobOut(ORM):
    id: uuid.UUID
    job_type: str
    status: str
    attempts: int
    last_error: str | None
    result: dict | None
    created_at: datetime
    updated_at: datetime


class AgentRunOut(ORM):
    id: uuid.UUID
    agent_name: str
    lead_id: uuid.UUID | None
    campaign_id: uuid.UUID | None
    provider: str
    model: str
    prompt_version: str
    status: str
    attempts: int
    error: str | None
    started_at: datetime
    completed_at: datetime | None
    latency_ms: int | None
    # Redacted structured output (None when payload logging is off, the run failed, or it was erased).
    output: dict[str, Any] | None = None
