"""Follow-up processing. The backend decides IF a follow-up may happen; the agent only writes it."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AgentFailedError, GrowthOSError
from app.models import Campaign, Contact, Email, EmailDraft, Followup, Lead, Organization
from app.models.enums import CampaignStatus, EmailStatus, FollowupStatus, LeadStatus, TraceStatus, WorkflowState
from app.services.common import (
    business_profile_context,
    campaign_context,
    contact_context,
    latest_research,
    lead_context,
)
from app.services.container import Container
from app.services.llm.run_logger import RunContext
from app.services.safety import contact_has_replied, max_followups_for
from app.services.suppression import is_suppressed

logger = logging.getLogger(__name__)


def stop_reason(db: Session, followup: Followup) -> str | None:
    """Return why this follow-up must be cancelled, or None if it may proceed."""
    contact = db.get(Contact, followup.contact_id)
    lead = db.get(Lead, followup.lead_id)
    campaign = db.get(Campaign, followup.campaign_id)
    if contact.suppressed or contact.unsubscribed or is_suppressed(db, contact.organization_id, contact.email_hash):
        return "suppressed"
    if contact_has_replied(db, contact.id, campaign.id):
        return "recipient_replied"
    if lead.disabled:
        return "lead_disabled"
    if campaign.status == CampaignStatus.COMPLETED:
        return "campaign_completed"
    return None


def _close_sequence(db: Session, followup: Followup) -> None:
    followup.status = FollowupStatus.LIMIT_REACHED
    db.execute(
        update(Email)
        .where(Email.campaign_id == followup.campaign_id, Email.contact_id == followup.contact_id,
               Email.status.in_([EmailStatus.SENT, EmailStatus.DELIVERED]))
        .values(status=EmailStatus.COMPLETED)
    )
    lead = db.get(Lead, followup.lead_id)
    if lead.status == LeadStatus.CONTACTED:
        lead.status = LeadStatus.COMPLETED


def generate_followup_email(db: Session, followup: Followup, container: Container) -> Email:
    lead = db.get(Lead, followup.lead_id)
    contact = db.get(Contact, followup.contact_id)
    campaign = db.get(Campaign, followup.campaign_id)
    previous = db.scalars(
        select(Email).where(Email.campaign_id == campaign.id, Email.contact_id == contact.id,
                            Email.sequence_number < followup.sequence_number).order_by(Email.sequence_number)
    ).all()
    research = latest_research(db, lead.id)
    result = container.followup_agent().run(
        {
            "business_profile": business_profile_context(db, lead.organization_id),
            "lead": lead_context(lead),
            "contact": contact_context(contact),
            "research": research.data if research else None,
            "campaign": campaign_context(campaign),
            "followup_number": followup.sequence_number,
            "max_followups": max_followups_for(campaign),
            "previous_emails": [{"subject": e.subject, "body": e.body} for e in previous],
        },
        RunContext(organization_id=lead.organization_id, lead_id=lead.id, campaign_id=campaign.id),
    )
    out = result.output
    draft = EmailDraft(organization_id=lead.organization_id, lead_id=lead.id, contact_id=contact.id,
                       agent_run_id=result.run_id, agent_name="followup",
                       sequence_number=followup.sequence_number, subject=out.subject, body=out.body,
                       personalization_used=out.personalization_used, confidence=out.confidence)
    db.add(draft)
    db.flush()
    email = Email(organization_id=lead.organization_id, campaign_id=campaign.id, lead_id=lead.id,
                  contact_id=contact.id, draft_id=draft.id, sequence_number=followup.sequence_number,
                  subject=out.subject, body=out.body, status=EmailStatus.DRAFT)
    db.add(email)
    db.flush()
    followup.email_id = email.id
    followup.status = FollowupStatus.GENERATED
    return email


def process_followup(db: Session, followup: Followup, container: Container) -> str:
    """Handle one due follow-up. Returns an outcome label. Caller commits."""
    from app.services import workflow_service as wfs

    if followup.status != FollowupStatus.PENDING:
        return "skipped_not_pending"
    lead = db.get(Lead, followup.lead_id)
    reason = stop_reason(db, followup)
    if reason:
        followup.status = FollowupStatus.CANCELLED
        followup.cancel_reason = reason
        wfs.advance_lead(db, lead, "followup", "Check follow-up", TraceStatus.BLOCKED,
                         f"Follow-up {followup.sequence_number} stopped by rule: {reason.replace('_', ' ')}")
        return f"cancelled:{reason}"
    campaign = db.get(Campaign, followup.campaign_id)
    if campaign.status == CampaignStatus.PAUSED:
        return "waiting:campaign_paused"  # stays PENDING; resumes when the campaign resumes
    if followup.sequence_number > max_followups_for(campaign):
        _close_sequence(db, followup)
        wfs.advance_lead(db, lead, "followup", "Check follow-up", TraceStatus.COMPLETED,
                         f"No reply after {followup.sequence_number - 1} follow-up(s): limit reached, sequence closed",
                         state=WorkflowState.COMPLETED)
        return "limit_reached"
    try:
        email = generate_followup_email(db, followup, container)
    except (AgentFailedError, GrowthOSError) as exc:
        followup.status = FollowupStatus.FAILED
        followup.cancel_reason = f"generation_failed: {exc.message}"[:200]
        wfs.advance_lead(db, lead, "followup", "Write follow-up", TraceStatus.FAILED, exc.message)
        return "failed"
    wfs.advance_lead(db, lead, "followup", "Write follow-up", TraceStatus.COMPLETED,
                     f"Drafted follow-up {followup.sequence_number}: “{email.subject}” (uses previous emails from memory)",
                     state=WorkflowState.DRAFTING)

    from app.services.orchestrator import Orchestrator
    from app.services.policy import evaluate_outbound

    org = db.get(Organization, followup.organization_id)
    decision = evaluate_outbound(db, email)
    if org.automated_sending_enabled and decision.outcome == "ALLOW":
        from app.services.email_service import approve_email, send_email

        wfs.advance_lead(db, lead, "safety", "Check follow-up against policy", TraceStatus.COMPLETED,
                         "ALLOW: automation rules permit sending without review", state=WorkflowState.SAFETY_CHECK)
        approve_email(email, None, db)
        db.commit()
        try:
            send_email(db, email.id, org.id, container)  # still runs can_send()
            return "generated_and_sent"
        except GrowthOSError as exc:
            logger.info("Automatic follow-up send blocked/failed: %s", exc.message)
            return "generated_send_blocked"
    # Human decides: automation off, or the Safety Agent escalated/blocked it.
    wf = wfs.active_lead_workflow(db, lead.id)
    Orchestrator(db, container).safety_and_route(wf, lead, email)
    return "generated"


def process_due_followups(db: Session, container: Container, now: datetime | None = None, limit: int = 50,
                          organization_id=None) -> dict:
    """Process due follow-ups one at a time (each locked with SKIP LOCKED, committed individually).
    Follow-ups of paused campaigns are left PENDING until the campaign resumes."""
    now = now or datetime.now(timezone.utc)
    outcomes: dict[str, int] = {}
    touched: set = set()
    for _ in range(limit):
        stmt = (
            select(Followup)
            .join(Campaign, Campaign.id == Followup.campaign_id)
            .where(Followup.status == FollowupStatus.PENDING, Followup.due_at <= now,
                   Campaign.status != CampaignStatus.PAUSED)
        )
        if organization_id is not None:
            stmt = stmt.where(Followup.organization_id == organization_id)
        followup = db.scalar(stmt.order_by(Followup.due_at).limit(1).with_for_update(skip_locked=True, of=Followup))
        if followup is None:
            break
        org_id = followup.organization_id
        outcome = process_followup(db, followup, container)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        db.commit()
        if outcome == "generated":
            touched.add(org_id)
    # Follow-up drafts that wait for a human go to the Human Approval Center like first-touch drafts.
    from app.services.email_service import ensure_review_approvals

    for org_id in touched:
        ensure_review_approvals(db, org_id)
    return outcomes
