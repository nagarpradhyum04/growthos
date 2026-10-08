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
    CONVERTED = "CONVERTED"  # became a customer


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


# ---------------- Orchestration ----------------
class WorkflowType(StrEnum):
    GOAL = "GOAL"  # a business goal broken into many lead workflows
    LEAD = "LEAD"  # one lead's journey from research to reply
    INBOUND = "INBOUND"  # an incoming email / customer message
    LIFECYCLE = "LIFECYCLE"  # post-purchase customer journey


class WorkflowState(StrEnum):
    PENDING = "PENDING"
    RESEARCHING = "RESEARCHING"
    QUALIFYING = "QUALIFYING"
    DRAFTING = "DRAFTING"
    SAFETY_CHECK = "SAFETY_CHECK"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY_TO_SEND = "READY_TO_SEND"
    SENT = "SENT"
    WAITING_FOR_REPLY = "WAITING_FOR_REPLY"
    REPLY_RECEIVED = "REPLY_RECEIVED"
    ESCALATED = "ESCALATED"
    FOLLOW_UP_SCHEDULED = "FOLLOW_UP_SCHEDULED"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


TERMINAL_WORKFLOW_STATES = {WorkflowState.COMPLETED, WorkflowState.BLOCKED, WorkflowState.FAILED}


class TraceStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    WAITING = "WAITING"
    ESCALATED = "ESCALATED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


# ---------------- Email intelligence & escalation ----------------
class PriorityTier(StrEnum):
    GREEN = "GREEN"  # routine
    YELLOW = "YELLOW"  # important opportunity
    RED = "RED"  # needs human attention


class ApprovalType(StrEnum):
    OUTBOUND_EMAIL = "OUTBOUND_EMAIL"
    REPLY_ESCALATION = "REPLY_ESCALATION"
    MESSAGE_ESCALATION = "MESSAGE_ESCALATION"
    WARRANTY_CLAIM = "WARRANTY_CLAIM"
    SERVICE_REQUEST = "SERVICE_REQUEST"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TAKEN_OVER = "TAKEN_OVER"
    AUTOMATED = "AUTOMATED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class Priority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


# ---------------- Customers ----------------
class UserRole(StrEnum):
    OWNER = "owner"
    CUSTOMER = "customer"


class CustomerStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PurchaseStatus(StrEnum):
    ACTIVE = "ACTIVE"
    IN_SERVICE = "IN_SERVICE"
    RETIRED = "RETIRED"


class WarrantyStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MORE_INFORMATION_REQUIRED = "MORE_INFORMATION_REQUIRED"
    COMPLETED = "COMPLETED"


class ServiceStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    RESCHEDULED = "RESCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MessageSender(StrEnum):
    CUSTOMER = "customer"
    BUSINESS = "business"
    AI = "ai"
