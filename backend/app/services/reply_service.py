"""Inbound replies: record (with immediate safety actions), then analyze with the Reply Analysis Agent."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Contact, Email, EmailReply, Lead
from app.models.enums import (
    SENT_LIKE_STATUSES,
    UNSENT_STATUSES,
    EmailStatus,
    LeadStatus,
    ReplyClassification,
    SuppressionReason,
)
from app.models.enums import ApprovalType, Priority, PriorityTier, TraceStatus, WorkflowState
from app.services import approval_service, memory_service
from app.services import workflow_service as wfs
from app.services.common import get_owned, lead_context
from app.services.escalation import triage
from app.services.policy import get_policy
from app.services.container import Container
from app.services.llm.run_logger import RunContext
from app.services.opt_out import OptOutType, detect_opt_out
from app.services.suppression import cancel_pending_followups, forget_contact, hash_email, suppress_contact


def _resolve_email(db: Session, organization_id: uuid.UUID, email_id: uuid.UUID | None,
                   from_address: str | None) -> Email:
    if email_id:
        return get_owned(db, Email, email_id, organization_id)
    if from_address:
        email = db.scalar(
            select(Email)
            .join(Contact, Contact.id == Email.contact_id)
            .where(Email.organization_id == organization_id, Contact.email_hash == hash_email(from_address),
                   Email.status.in_(SENT_LIKE_STATUSES))
            .order_by(Email.sent_at.desc())
        )
        if email:
            return email
    raise NotFoundError("Could not match this reply to a sent email")


def record_reply(db: Session, organization_id: uuid.UUID, *, subject: str, body: str,
                 email_id: uuid.UUID | None = None, from_address: str | None = None,
                 received_at: datetime | None = None, external_id: str | None = None) -> tuple[EmailReply, bool]:
    """Store a reply and immediately apply the hard rules. Returns (reply, created)."""
    if external_id:
        existing = db.scalar(select(EmailReply).where(EmailReply.external_id == external_id,
                                                      EmailReply.organization_id == organization_id))
        if existing:
            return existing, False  # webhook retry / duplicate request

    email = _resolve_email(db, organization_id, email_id, from_address)
    if email.status not in SENT_LIKE_STATUSES:
        raise NotFoundError("Replies can only be recorded for emails that were sent")
    contact = db.get(Contact, email.contact_id)
    lead = db.get(Lead, email.lead_id)

    reply = EmailReply(organization_id=organization_id, email_id=email.id, lead_id=lead.id, contact_id=contact.id,
                       campaign_id=email.campaign_id, external_id=external_id, subject=subject or "",
                       body=body or "", received_at=received_at or datetime.now(timezone.utc))
    db.add(reply)
    email.status = EmailStatus.REPLIED
    if lead.status != LeadStatus.SUPPRESSED:
        lead.status = LeadStatus.REPLIED
    lead.last_activity_at = datetime.now(timezone.utc)

    # Rule: any reply stops the automated sequence immediately.
    cancel_pending_followups(db, contact.id, "recipient_replied")
    db.execute(
        update(Email)
        .where(Email.contact_id == contact.id, Email.campaign_id == email.campaign_id, Email.sequence_number > 0,
               Email.status.in_(UNSENT_STATUSES))
        .values(status=EmailStatus.COMPLETED, last_error="Not sent: recipient replied")
    )
    db.flush()

    wfs.advance_lead(db, lead, "email_intelligence", "Reply received", TraceStatus.COMPLETED,
                     "Inbound reply matched to the sent email; pending follow-ups stopped by rule",
                     state=WorkflowState.REPLY_RECEIVED)

    # Rule: explicit opt-out language suppresses right now, without waiting for the LLM.
    opt_out = detect_opt_out(f"{subject}\n{body}")
    if opt_out:
        reply.opt_out_detected = True
        reply.classification = ReplyClassification.UNSUBSCRIBE
        reply.recommended_action = "Do not contact this person again."
        reply.summary = ("The contact asked to have their data deleted (Forget Me)." if opt_out == OptOutType.FORGET
                         else "The contact asked to stop receiving emails.")
        reply.analyzed_at = datetime.now(timezone.utc)
        reply.tier = PriorityTier.GREEN
        reply.intents = ["opt_out"]
        reply.escalation_reason = "Opt-out request: handled automatically by suppression rules (no human needed)"
        wfs.advance_lead(db, lead, "safety", "Opt-out rule", TraceStatus.BLOCKED,
                         "Explicit opt-out detected (deterministic rule): contact suppressed, all outreach blocked",
                         state=WorkflowState.BLOCKED)
        if opt_out == OptOutType.FORGET:
            forget_contact(db, contact, source="reply")
            reply.summary = "The contact asked to be forgotten. Their data was erased."
        else:
            suppress_contact(db, contact, SuppressionReason.UNSUBSCRIBED, source="reply")
    db.flush()
    return reply, True


def analyze_reply(db: Session, reply: EmailReply, container: Container) -> EmailReply:
    contact = db.get(Contact, reply.contact_id)
    if contact.forgotten_at is not None:
        # Nothing left to analyze; never send erased data to the LLM.
        reply.classification = reply.classification or ReplyClassification.UNSUBSCRIBE
        reply.analyzed_at = reply.analyzed_at or datetime.now(timezone.utc)
        return reply

    email = db.get(Email, reply.email_id) if reply.email_id else None
    lead = db.get(Lead, reply.lead_id)
    result = container.reply_analysis_agent().run(
        original_email={"subject": email.subject, "body": email.body} if email else {},
        reply={"subject": reply.subject, "body": reply.body},
        lead=lead_context(lead),
        ctx=RunContext(organization_id=reply.organization_id, lead_id=lead.id, campaign_id=reply.campaign_id),
    )
    out = result.output
    # The deterministic detector's UNSUBSCRIBE can never be downgraded by the LLM.
    if not reply.opt_out_detected:
        reply.classification = out.classification
    reply.summary = out.summary
    reply.recommended_action = out.recommended_action
    reply.agent_run_id = result.run_id
    reply.analyzed_at = datetime.now(timezone.utc)
    reply.sentiment = out.sentiment
    reply.suggested_response = out.suggested_response or None

    if out.classification == ReplyClassification.UNSUBSCRIBE and not contact.suppressed:
        suppress_contact(db, contact, SuppressionReason.UNSUBSCRIBED, source="reply_analysis")

    # Email Intelligence tiering: backend rules over text + LLM intents.
    policy = get_policy(db, reply.organization_id)
    t = triage(f"{reply.subject}\n{reply.body}", llm_intents=list(out.intents),
               classification=reply.classification.value, sentiment=out.sentiment,
               escalation_rules=policy.escalation_rules, large_order_threshold=float(policy.large_order_threshold))
    reply.tier = PriorityTier(t.tier)
    reply.intents = t.intents
    reply.escalation_reason = t.reason
    reply.requires_human_attention = bool(out.requires_human_attention or t.escalate)

    memory_service.remember(db, reply.organization_id, scope="lead", subject_id=lead.id, category="conversation",
                            key=f"reply:{reply.id}", content=f"Replied ({reply.classification.value}, {t.tier}): {out.summary}",
                            source="email_intelligence", data={"intents": t.intents, "sentiment": out.sentiment})
    wfs.advance_lead(db, lead, "email_intelligence", "Classify reply",
                     TraceStatus.ESCALATED if t.escalate else TraceStatus.COMPLETED,
                     f"{reply.classification.value.replace('_', ' ')} · {t.tier} — {t.reason}",
                     detail={"tier": t.tier, "intents": t.intents, "evidence": t.evidence})
    if t.escalate:
        approval_service.create(
            db, reply.organization_id, ApprovalType.REPLY_ESCALATION,
            title=f"{lead.company_name} replied: {reply.classification.value.replace('_', ' ').lower()}",
            reason=t.reason, tier=PriorityTier(t.tier), category=t.category,
            priority=Priority.URGENT if t.tier == "RED" else Priority.HIGH,
            recommended_action=out.recommended_action, suggested_response=out.suggested_response or "",
            reply_id=reply.id, lead_id=lead.id)
        wfs.advance_lead(db, lead, "human", "Escalate to business owner", TraceStatus.WAITING,
                         "Waiting for the owner to respond or take over", state=WorkflowState.ESCALATED)
    elif reply.classification == ReplyClassification.OUT_OF_OFFICE:
        wfs.advance_lead(db, lead, "orchestrator", "Decide next step", TraceStatus.COMPLETED,
                         "Auto-reply: nothing to do until the contact is back", state=WorkflowState.WAITING_FOR_REPLY)
    elif not contact.suppressed:
        wfs.advance_lead(db, lead, "orchestrator", "Decide next step", TraceStatus.COMPLETED,
                         "Routine reply handled; no human action required", state=WorkflowState.COMPLETED)
    db.flush()
    return reply
