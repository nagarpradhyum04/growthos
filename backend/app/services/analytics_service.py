"""Campaign metrics (computed deterministically from the database) + LLM insights on top."""
import uuid

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import (
    Approval,
    Campaign,
    Contact,
    Conversation,
    Customer,
    Email,
    EmailDraft,
    EmailReply,
    Followup,
    Lead,
    LifecycleEvent,
    Message,
    Purchase,
    ResearchResult,
    ServiceRequest,
    WarrantyClaim,
)
from app.models.enums import (
    SENT_LIKE_STATUSES,
    ApprovalStatus,
    CampaignStatus,
    EmailStatus,
    FollowupStatus,
    LeadStatus,
    MessageSender,
    PriorityTier,
    ReplyClassification,
)
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


def _campaign_extras(db: Session, organization_id: uuid.UUID, campaign_id) -> dict:
    """Funnel stages beyond replies + learning signals for one campaign (or all when campaign_id is None)."""
    reply_stmt = select(EmailReply.intents, EmailReply.classification).where(EmailReply.organization_id == organization_id)
    lead_stmt = select(func.count(Lead.id)).where(Lead.organization_id == organization_id, Lead.status == LeadStatus.CONVERTED)
    draft_stmt = (select(EmailDraft.personalization_used).join(Email, Email.draft_id == EmailDraft.id)
                  .where(Email.organization_id == organization_id, Email.sequence_number == 0,
                         Email.status.in_(SENT_LIKE_STATUSES)))
    if campaign_id is not None:
        reply_stmt = reply_stmt.where(EmailReply.campaign_id == campaign_id)
        lead_stmt = lead_stmt.where(Lead.campaign_id == campaign_id)
        draft_stmt = draft_stmt.where(Email.campaign_id == campaign_id)
    replies = db.execute(reply_stmt).all()
    meetings = sum(1 for intents, _ in replies if "meeting_request" in (intents or []))
    positive = sum(1 for _, c in replies if c in (ReplyClassification.INTERESTED, ReplyClassification.ASKED_QUESTION))
    drafts = db.scalars(draft_stmt).all()
    personalized = sum(1 for p in drafts if p)
    return {"meeting_requests": meetings, "positive_replies": positive, "conversions": db.scalar(lead_stmt) or 0,
            "personalized_pct": _pct(personalized, len(drafts))}


def _email_intelligence(db: Session, organization_id: uuid.UUID) -> dict:
    counts = {"routine": 0, "opportunity": 0, "human_attention": 0, "opt_out": 0, "unclassified": 0}
    rows = [(r.tier, r.intents) for r in db.execute(select(EmailReply.tier, EmailReply.intents)
                                                   .where(EmailReply.organization_id == organization_id))]
    rows += [(m.tier, m.intents) for m in db.execute(select(Message.tier, Message.intents).where(
        Message.organization_id == organization_id, Message.sender == MessageSender.CUSTOMER,
        Message.tier.is_not(None)))]
    for tier, intents in rows:
        if "opt_out" in (intents or []):
            counts["opt_out"] += 1
        elif tier is None:
            counts["unclassified"] += 1
        else:
            counts[{"GREEN": "routine", "YELLOW": "opportunity", "RED": "human_attention"}[tier.value]] += 1
    return counts


def _lifecycle(db: Session, organization_id: uuid.UUID) -> dict:
    def count(stmt) -> int:
        return db.scalar(stmt) or 0

    repeat = select(Purchase.customer_id).where(Purchase.organization_id == organization_id) \
        .group_by(Purchase.customer_id).having(func.count(Purchase.id) > 1).subquery()
    return {
        "customers": count(select(func.count(Customer.id)).where(Customer.organization_id == organization_id)),
        "purchases": count(select(func.count(Purchase.id)).where(Purchase.organization_id == organization_id)),
        "support_questions": count(select(func.count(Message.id)).join(Conversation, Conversation.id == Message.conversation_id)
                                   .where(Message.organization_id == organization_id, Conversation.channel == "support_ai",
                                          Message.sender == MessageSender.CUSTOMER)),
        "customer_messages": count(select(func.count(Message.id)).join(Conversation, Conversation.id == Message.conversation_id)
                                   .where(Message.organization_id == organization_id, Conversation.channel == "business",
                                          Message.sender == MessageSender.CUSTOMER)),
        "warranty_requests": count(select(func.count(WarrantyClaim.id)).where(WarrantyClaim.organization_id == organization_id)),
        "service_requests": count(select(func.count(ServiceRequest.id)).where(ServiceRequest.organization_id == organization_id)),
        "lifecycle_messages_sent": count(select(func.count(LifecycleEvent.id)).where(
            LifecycleEvent.organization_id == organization_id, LifecycleEvent.status == "SENT")),
        "repeat_customers": count(select(func.count()).select_from(repeat)),
    }


def compute_analytics(db: Session, organization_id: uuid.UUID) -> dict:
    campaigns = db.scalars(
        select(Campaign).where(Campaign.organization_id == organization_id).order_by(Campaign.created_at)
    ).all()
    per_campaign = []
    for c in campaigns:
        m = _metrics(db, organization_id, c.id)
        per_campaign.append({"campaign_id": str(c.id), "name": c.name, "status": c.status.value,
                             "target_audience": c.target_audience, **m,
                             **_campaign_extras(db, organization_id, c.id)})
    pending = db.execute(select(Approval.tier, func.count(Approval.id)).where(
        Approval.organization_id == organization_id, Approval.status == ApprovalStatus.PENDING)
        .group_by(Approval.tier)).all()
    return {
        "overall": {
            **_metrics(db, organization_id, None),
            **_campaign_extras(db, organization_id, None),
            "campaigns_total": len(campaigns),
            "active_campaigns": sum(1 for c in campaigns if c.status == CampaignStatus.ACTIVE),
            "pending_approvals": sum(n for _, n in pending),
            "open_opportunities": sum(n for t, n in pending if t == PriorityTier.YELLOW),
        },
        "campaigns": per_campaign,
        "email_intelligence": _email_intelligence(db, organization_id),
        "lifecycle": _lifecycle(db, organization_id),
    }


def generate_insights(db: Session, organization_id: uuid.UUID, container: Container, workflow=None) -> dict:
    """Analytics Agent explains real metrics; its learnings are stored in shared memory (category=insight),
    where future Outreach runs read them. Numbers the agent did not get from the data are rejected."""
    from app.models.enums import TraceStatus, WorkflowState, WorkflowType
    from app.services import memory_service
    from app.services import workflow_service as wfs

    metrics = compute_analytics(db, organization_id)
    llm_metrics = {
        "overall": {k: v for k, v in metrics["overall"].items() if v is not None},
        "campaigns": [
            {k: v for k, v in c.items() if k not in ("campaign_id",) and v is not None} for c in metrics["campaigns"]
        ],
    }
    comparisons = [{"campaign": c["name"], "target_audience": c["target_audience"], "emails_sent": c["emails_sent"],
                    "reply_rate_pct": c["reply_rate_pct"], "personalized_pct": c["personalized_pct"],
                    "conversions": c["conversions"]}
                   for c in metrics["campaigns"] if c["emails_sent"] > 0]
    wf = workflow or wfs.start_workflow(db, organization_id, WorkflowType.GOAL, goal="Analyze performance and learn",
                                        command="insights")
    wfs.record(db, wf, "analytics", "Compute metrics (deterministic)", TraceStatus.COMPLETED,
               f"{metrics['overall']['emails_sent']} emails, {metrics['overall']['replies']} replies, "
               f"{len(comparisons)} campaign(s) with sends")
    result = container.analytics_agent().run(llm_metrics, RunContext(organization_id=organization_id),
                                             comparisons=comparisons)
    output: AnalyticsOutput = result.output
    stored = []
    if metrics["overall"]["emails_sent"] > 0:
        for i, rec in enumerate(output.recommendations[:3]):
            entry = memory_service.remember(
                db, organization_id, scope="business", subject_id=None, category="insight", key=f"recommendation:{i}",
                content=rec, source="analytics", importance=3 - i, workflow_id=wf.id,
                data={"basis": {"emails_sent": metrics["overall"]["emails_sent"],
                                "reply_rate_pct": metrics["overall"]["reply_rate_pct"]}, "comparisons": comparisons})
            stored.append(entry.content)
        for i, item in enumerate(output.what_worked[:2]):
            memory_service.remember(db, organization_id, scope="business", subject_id=None, category="insight",
                                    key=f"what_worked:{i}", content=item, source="analytics", importance=1,
                                    workflow_id=wf.id)
    wfs.record(db, wf, "analytics", "Explain performance", TraceStatus.COMPLETED, output.summary[:300],
               agent_run_id=result.run_id)
    wfs.record(db, wf, "memory", "Store learnings", TraceStatus.COMPLETED if stored else TraceStatus.SKIPPED,
               f"Stored {len(stored)} insight(s) for future campaigns" if stored else "No data yet — nothing to learn",
               detail={"insights": stored}, state=WorkflowState.COMPLETED)
    db.commit()
    return {"metrics": metrics, "insights": output.model_dump(), "stored_insights": stored,
            "agent_run_id": str(result.run_id) if result.run_id else None, "workflow_id": str(wf.id)}
