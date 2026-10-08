"""Domain enums shared by models, services and API schemas."""
from enum import StrEnum


class CampaignStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class LeadStatus(StrEnum):
    NEW = "NEW"
    RESEARCHED = "RESEARCHED"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    DRAFTED = "DRAFTED"
    CONTACTED = "CONTACTED"
    REPLIED = "REPLIED"
    COMPLETED = "COMPLETED"
    SUPPRESSED = "SUPPRESSED"


class EmailStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    REPLIED = "REPLIED"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"
    COMPLETED = "COMPLETED"


# Emails in these states have left (or are leaving) the building.
SENT_LIKE_STATUSES = {
    EmailStatus.SENT,
    EmailStatus.DELIVERED,
    EmailStatus.REPLIED,
    EmailStatus.COMPLETED,
}
# Emails in these states are still waiting to go out and must be cancelled on suppression.
UNSENT_STATUSES = {EmailStatus.DRAFT, EmailStatus.APPROVED, EmailStatus.SCHEDULED, EmailStatus.FAILED}


class FollowupStatus(StrEnum):
    PENDING = "PENDING"  # waiting for due_at
    GENERATED = "GENERATED"  # draft email created
    CANCELLED = "CANCELLED"  # stopped (reply, suppression, disabled...)
    LIMIT_REACHED = "LIMIT_REACHED"  # sequence finished with no reply
    FAILED = "FAILED"  # agent failed to generate


class ReplyClassification(StrEnum):
    INTERESTED = "INTERESTED"
    NOT_INTERESTED = "NOT_INTERESTED"
    ASKED_QUESTION = "ASKED_QUESTION"
    REQUESTED_LATER = "REQUESTED_LATER"
    UNSUBSCRIBE = "UNSUBSCRIBE"
    OUT_OF_OFFICE = "OUT_OF_OFFICE"
    UNKNOWN = "UNKNOWN"


class SuppressionReason(StrEnum):
    FORGET_ME = "user_requested_forget"
    UNSUBSCRIBED = "unsubscribed"
    MANUAL = "manual"


class AgentRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
