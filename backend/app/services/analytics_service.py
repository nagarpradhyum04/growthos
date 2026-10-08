"""Campaign metrics (computed deterministically from the database) + LLM insights on top."""
import uuid

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import Campaign, Contact, Email, EmailReply, Followup, Lead, ResearchResult
from app.models.enums import SENT_LIKE_STATUSES, CampaignStatus, EmailStatus, FollowupStatus, ReplyClassification
from app.services.agents.schemas import AnalyticsOutput
from app.services.container import Container
from app.services.llm.run_logger import RunContext


def _pct(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 1) if denominator else None


def _metrics(db: Session, organization_id: uuid.UUID, campaign_id: uuid.UUID | None) -> dict:
    def scoped(stmt, model):
        stmt = stmt.where(model.organization_id == organization_id)
        if campaign_id is not None:
            stmt = stmt.where(model.campaign_id == campaign_id)
        return stmt

    def count(stmt) -> int:
        return db.scalar(stmt) or 0

    sent = Email.status.in_(SENT_LIKE_STATUSES)
    leads_total = count(scoped(select(func.count(Lead.id)), Lead))
    leads_researched = count(scoped(select(func.count(distinct(Lead.id))).join(
        ResearchResult, ResearchResult.lead_id == Lead.id), Lead))
    leads_qualified = count(scoped(select(func.count(Lead.id)).where(Lead.qualified.is_(True)), Lead))
    leads_disqualified = count(scoped(select(func.count(Lead.id)).where(Lead.qualified.is_(False)), Lead))
    emails_sent = count(scoped(select(func.count(Email.id)).where(sent), Email))
    initial_sent = count(scoped(select(func.count(Email.id)).where(sent, Email.sequence_number == 0), Email))
    followups_sent = count(scoped(select(func.count(Email.id)).where(sent, Email.sequence_number > 0), Email))
    contacts_emailed = count(scoped(select(func.count(distinct(Email.contact_id))).where(sent), Email))
    drafts_awaiting_review = count(scoped(select(func.count(Email.id)).where(
        Email.status.in_([EmailStatus.DRAFT, EmailStatus.APPROVED])), Email))
    replies = count(scoped(select(func.count(EmailReply.id)), EmailReply))
    contacts_replied = count(scoped(select(func.count(distinct(EmailReply.contact_id))), EmailReply))
    interested = count(scoped(select(func.count(distinct(EmailReply.contact_id))).where(
        EmailReply.classification == ReplyClassification.INTERESTED), EmailReply))
    followups_pending = count(scoped(select(func.count(Followup.id)).where(
        Followup.status == FollowupStatus.PENDING), Followup))
    suppressed_stmt = select(func.count(Contact.id)).join(Lead, Lead.id == Contact.lead_id).where(
        Contact.organization_id == organization_id, Contact.suppressed.is_(True))
    if campaign_id is not None:
        suppressed_stmt = suppressed_stmt.where(Lead.campaign_id == campaign_id)
    breakdown_rows = db.execute(
        scoped(select(EmailReply.classification, func.count(EmailReply.id)), EmailReply)
        .group_by(EmailReply.classification)
    ).all()

    return {
        "leads_total": leads_total,
        "leads_researched": leads_researched,
        "leads_qualified": leads_qualified,
        "leads_disqualified": leads_disqualified,
        "drafts_awaiting_review": drafts_awaiting_review,
        "emails_sent": emails_sent,
        "initial_emails_sent": initial_sent,
        "followups_sent": followups_sent,
        "followups_pending": followups_pending,
        "contacts_emailed": contacts_emailed,
        "replies": replies,
        "contacts_replied": contacts_replied,
        "reply_rate_pct": _pct(contacts_replied, contacts_emailed),
        "interested_contacts": interested,
        "conversion_rate_pct": _pct(interested, contacts_emailed),
        "contacts_suppressed": count(suppressed_stmt),
        "reply_breakdown": {(c.value if c else "UNANALYZED"): n for c, n in breakdown_rows},
        # Open tracking is intentionally not implemented (privacy + unreliable); never guess it.
        "opens": None,
    }


def compute_analytics(db: Session, organization_id: uuid.UUID) -> dict:
    campaigns = db.scalars(
        select(Campaign).where(Campaign.organization_id == organization_id).order_by(Campaign.created_at)
    ).all()
    per_campaign = []
    for c in campaigns:
        m = _metrics(db, organization_id, c.id)
        per_campaign.append({"campaign_id": str(c.id), "name": c.name, "status": c.status.value,
                             "target_audience": c.target_audience, **m})
    return {
        "overall": {
            **_metrics(db, organization_id, None),
            "campaigns_total": len(campaigns),
            "active_campaigns": sum(1 for c in campaigns if c.status == CampaignStatus.ACTIVE),
        },
        "campaigns": per_campaign,
    }


def generate_insights(db: Session, organization_id: uuid.UUID, container: Container) -> dict:
    metrics = compute_analytics(db, organization_id)
    llm_metrics = {
        "overall": {k: v for k, v in metrics["overall"].items() if v is not None},
        "campaigns": [
            {k: v for k, v in c.items() if k not in ("campaign_id",) and v is not None} for c in metrics["campaigns"]
        ],
    }
    result = container.analytics_agent().run(llm_metrics, RunContext(organization_id=organization_id))
    output: AnalyticsOutput = result.output
    return {"metrics": metrics, "insights": output.model_dump(), "agent_run_id": str(result.run_id) if result.run_id else None}
