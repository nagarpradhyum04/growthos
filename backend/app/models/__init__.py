"""All ORM models. Import from here so Alembic sees every table."""
from app.models.agent_run import AgentRun
from app.models.base import Base
from app.models.campaign import Campaign
from app.models.email import Email, EmailDraft, EmailReply, Followup
from app.models.job import Job
from app.models.lead import Contact, Lead, ResearchResult
from app.models.organization import BusinessProfile, Organization, User
from app.models.suppression import SuppressionRecord

__all__ = [
    "AgentRun",
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
