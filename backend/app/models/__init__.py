"""All ORM models. Import from here so Alembic sees every table."""
from app.models.agent_run import AgentRun
from app.models.approval import Approval
from app.models.customer import (
    Conversation,
    Customer,
    LifecycleEvent,
    Message,
    Notification,
    Product,
    Purchase,
    ServiceRequest,
    WarrantyClaim,
)
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.memory import MemoryEntry
from app.models.policy import BusinessPolicy
from app.models.portal_access import PortalAccessRequest
from app.models.workflow import Workflow, WorkflowEvent
from app.models.base import Base
from app.models.campaign import Campaign
from app.models.email import Email, EmailDraft, EmailReply, Followup
from app.models.job import Job
from app.models.lead import Contact, Lead, ResearchResult
from app.models.organization import BusinessProfile, Organization, User
from app.models.suppression import SuppressionRecord

__all__ = [
    "AgentRun",
    "Approval",
    "BusinessPolicy",
    "Conversation",
    "Customer",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "LifecycleEvent",
    "MemoryEntry",
    "Message",
    "Notification",
    "PortalAccessRequest",
    "Product",
    "Purchase",
    "ServiceRequest",
    "WarrantyClaim",
    "Workflow",
    "WorkflowEvent",
    "Base",
    "BusinessProfile",
    "Campaign",
    "Contact",
    "Email",
    "EmailDraft",
    "EmailReply",
    "Followup",
    "Job",
    "Lead",
    "Organization",
    "ResearchResult",
    "SuppressionRecord",
    "User",
]
