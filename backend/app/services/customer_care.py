"""Customer care workflows: conversations (Email Intelligence), Product Support AI, warranty, service.

Customer-visible text never includes internal reasoning, tiers, scores or agent traces.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AgentFailedError, InvalidStateError
from app.models import (
    Conversation,
    Customer,
    Message,
    Notification,
    Product,
    Purchase,
    ServiceRequest,
    WarrantyClaim,
)
from app.models.enums import (
    ApprovalStatus,
    ApprovalType,
    MessageSender,
    Priority,
    PriorityTier,
    PurchaseStatus,
    ServiceStatus,
    TraceStatus,
    WarrantyStatus,
    WorkflowState,
    WorkflowType,
)
from app.services import approval_service, knowledge_service, memory_service
from app.services import workflow_service as wfs
from app.services.container import Container
from app.services.customer_service import warranty_state
from app.services.escalation import triage
from app.services.llm.run_logger import RunContext
from app.services.policy import get_policy

NOT_FOUND_ANSWER = "I couldn't find that information in the available product documentation."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def notify(db: Session, organization_id, *, customer_id=None, kind: str, title: str, body: str = "", link: str = ""):
    db.add(Notification(organization_id=organization_id, customer_id=customer_id, kind=kind, title=title[:300],
                        body=body, link=link))


def customer_products(db: Session, customer: Customer) -> list[tuple[Purchase, Product]]:
    return list(db.execute(select(Purchase, Product).join(Product, Product.id == Purchase.product_id)
                           .where(Purchase.customer_id == customer.id).order_by(Purchase.purchased_at.desc())).all())


def get_conversation(db: Session, customer: Customer, channel: str, purchase_id=None,
                     subject: str = "") -> Conversation:
    stmt = select(Conversation).where(Conversation.customer_id == customer.id, Conversation.channel == channel)
    if channel == "support_ai":
        stmt = stmt.where(Conversation.purchase_id == purchase_id)
    conv = db.scalar(stmt.order_by(Conversation.created_at.desc()))
    if conv is None:
        conv = Conversation(organization_id=customer.organization_id, customer_id=customer.id, channel=channel,
                            purchase_id=purchase_id, subject=subject or ("Support" if channel == "support_ai" else "Messages"))
        db.add(conv)
        db.flush()
    return conv


def _add_message(db: Session, conv: Conversation, sender: MessageSender, body: str, **fields) -> Message:
    msg = Message(organization_id=conv.organization_id, conversation_id=conv.id, customer_id=conv.customer_id,
                  sender=sender, body=body, **fields)
    db.add(msg)
    conv.last_message_at = _now()
    db.flush()
    return msg


# ------------------------------------------------------------------ Product Support AI (RAG)
def answer_question(db: Session, customer: Customer, question: str, container: Container, *,
                    purchase: Purchase | None = None, workflow=None) -> dict:
    """Retrieve -> grounded answer. If nothing relevant is retrieved, no LLM call is made."""
    owned = customer_products(db, customer)
    product_ids = [p.id for _, p in owned]
    if purchase is not None:
        product_ids = [purchase.product_id]
    product = next((p for pu, p in owned if purchase is None or pu.id == purchase.id), None)
    hits = knowledge_service.retrieve(db, customer.organization_id, question, product_ids=product_ids or None, k=4)
    if workflow is not None:
        wfs.record(db, workflow, "support", "Retrieve documentation", TraceStatus.COMPLETED,
                   f"{len(hits)} relevant excerpt(s) found" + (f" (top: {hits[0].title})" if hits else ""),
                   detail={"sources": [{"title": h.title, "heading": h.heading, "score": h.score} for h in hits]})
    if not hits:
        return {"answerable": False, "answer": NOT_FOUND_ANSWER, "sources": [], "escalate": True}
    excerpts = [{"id": f"S{i + 1}", "title": h.title, "section": h.heading, "text": h.text} for i, h in enumerate(hits)]
    product_info = {"name": product.name, "description": product.description} if product else {}
    try:
        out = container.support_agent().run(question=question, product=product_info, excerpts=excerpts,
                                            ctx=RunContext(organization_id=customer.organization_id)).output
    except AgentFailedError:
        return {"answerable": False, "answer": NOT_FOUND_ANSWER, "sources": [], "escalate": True}
    if not out.answerable:
        return {"answerable": False, "answer": NOT_FOUND_ANSWER, "sources": [], "escalate": True}
    used = [e for e in excerpts if e["id"] in out.source_ids]
    return {"answerable": True, "answer": out.answer, "escalate": out.escalate,
            "sources": [{"title": e["title"], "section": e["section"]} for e in used]}


def support_chat(db: Session, customer: Customer, purchase: Purchase | None, question: str,
                 container: Container) -> tuple[Message, Message, dict]:
    conv = get_conversation(db, customer, "support_ai", purchase.id if purchase else None)
    q = _add_message(db, conv, MessageSender.CUSTOMER, question)
    wf = wfs.start_workflow(db, customer.organization_id, WorkflowType.INBOUND, goal="Product support question",
                            customer_id=customer.id)
    result = answer_question(db, customer, question, container, purchase=purchase, workflow=wf)
    a = _add_message(db, conv, MessageSender.AI, result["answer"], sources=result["sources"],
                     handled_automatically=True, analysis={"answerable": result["answerable"]})
    wfs.record(db, wf, "support", "Answer from documentation",
               TraceStatus.COMPLETED if result["answerable"] else TraceStatus.SKIPPED,
               "Grounded answer with sources" if result["answerable"] else "Not in documentation — said so instead of guessing",
               state=WorkflowState.COMPLETED)
    memory_service.remember(db, customer.organization_id, scope="customer", subject_id=customer.id,
                            category="conversation", key=f"support:{q.id}", content=f"Asked support: {question[:200]}",
                            source="support", data={"answered": result["answerable"]}, replace=False)
    return q, a, result


# ------------------------------------------------------------------ Business inbox + Email Intelligence
def customer_message(db: Session, customer: Customer, body: str, container: Container) -> Message:
    """A customer writes to the business. Email Intelligence classifies it; rules decide automate vs escalate."""
    conv = get_conversation(db, customer, "business")
    msg = _add_message(db, conv, MessageSender.CUSTOMER, body)
    wf = wfs.start_workflow(db, customer.organization_id, WorkflowType.INBOUND, goal="Incoming customer message",
                            customer_id=customer.id)
    policy = get_policy(db, customer.organization_id)
    context = memory_service.customer_context(db, customer)
    try:
        out = container.email_intelligence_agent().run(
            message=body, context=context, ctx=RunContext(organization_id=customer.organization_id)).output
        llm = {"intents": list(out.intents), "sentiment": out.sentiment, "summary": out.summary,
               "recommended_action": out.recommended_action, "suggested_response": out.suggested_response}
    except AgentFailedError as exc:
        llm = {"intents": [], "sentiment": None, "summary": "AI analysis unavailable", "recommended_action":
               "Read the message and respond personally.", "suggested_response": "", "error": exc.message}
    t = triage(body, llm_intents=llm["intents"], sentiment=llm["sentiment"],
               classification=None if llm["intents"] or "error" not in llm else "UNKNOWN",
               escalation_rules=policy.escalation_rules, large_order_threshold=float(policy.large_order_threshold))
    msg.tier = PriorityTier(t.tier)
    msg.intents = t.intents
    msg.analysis = {**llm, "reason": t.reason, "evidence": t.evidence, "escalated": t.escalate}
    wfs.record(db, wf, "email_intelligence", "Classify message",
               TraceStatus.ESCALATED if t.escalate else TraceStatus.COMPLETED, f"{t.tier} — {t.reason}",
               detail={"intents": t.intents, "evidence": t.evidence}, state=WorkflowState.REPLY_RECEIVED)
    memory_service.remember(db, customer.organization_id, scope="customer", subject_id=customer.id,
                            category="conversation", key=f"message:{msg.id}",
                            content=f"Customer wrote ({t.tier}, {', '.join(t.intents) or 'general'}): {llm['summary']}",
                            source="email_intelligence", replace=False)

    if t.escalate:
        approval_service.create(
            db, customer.organization_id, ApprovalType.MESSAGE_ESCALATION,
            title=f"{customer.name}: {', '.join(i.replace('_', ' ') for i in t.intents[:3]) or 'message'}",
            reason=t.reason, tier=PriorityTier(t.tier), category=t.category,
            priority=Priority.URGENT if t.tier == "RED" else Priority.HIGH,
            recommended_action=llm["recommended_action"], suggested_response=llm["suggested_response"],
            message_id=msg.id, customer_id=customer.id, workflow_id=wf.id)
        wfs.record(db, wf, "human", "Escalate to business owner", TraceStatus.WAITING,
                   "A human will reply", state=WorkflowState.ESCALATED)
        return msg

    if t.tier == "GREEN" and policy.auto_handle_routine:
        if {"routine_question", "brochure_request"} & set(t.intents):
            result = answer_question(db, customer, body, container, workflow=wf)
            if result["answerable"]:
                _add_message(db, conv, MessageSender.AI, result["answer"], sources=result["sources"],
                             handled_automatically=True)
                msg.handled_automatically = True
                wfs.record(db, wf, "support", "Auto-answer routine question", TraceStatus.COMPLETED,
                           "Answered from documentation (routine, automation allowed)", state=WorkflowState.COMPLETED)
                return msg
            approval_service.create(
                db, customer.organization_id, ApprovalType.MESSAGE_ESCALATION,
                title=f"{customer.name}: question not covered by documentation", tier=PriorityTier.GREEN,
                reason="Escalated because the documentation does not answer this routine question — a human must reply.",
                priority=Priority.MEDIUM, category="unanswered_question",
                recommended_action="Answer personally and consider adding it to the knowledge base.",
                suggested_response="", message_id=msg.id, customer_id=customer.id, workflow_id=wf.id)
            wfs.record(db, wf, "human", "Escalate unanswered question", TraceStatus.WAITING,
                       "Not found in documentation — routed to a human", state=WorkflowState.ESCALATED)
            return msg
        if {"greeting", "thanks"} & set(t.intents) and llm["suggested_response"]:
            _add_message(db, conv, MessageSender.AI, llm["suggested_response"], handled_automatically=True)
            msg.handled_automatically = True
            wfs.record(db, wf, "orchestrator", "Auto-acknowledge routine message", TraceStatus.COMPLETED,
                       "Routine message acknowledged automatically", state=WorkflowState.COMPLETED)
            return msg
    wfs.record(db, wf, "orchestrator", "Route", TraceStatus.COMPLETED, "Left in the inbox for the business",
               state=WorkflowState.COMPLETED)
    notify(db, customer.organization_id, kind="message", title=f"New message from {customer.name}", link="/inbox")
    return msg


def business_reply(db: Session, customer: Customer, body: str, user_id) -> Message:
    conv = get_conversation(db, customer, "business")
    msg = _add_message(db, conv, MessageSender.BUSINESS, body)
    notify(db, customer.organization_id, customer_id=customer.id, kind="message",
           title="New message from the business", body=body[:200], link="/portal/conversations")
    return msg


# ------------------------------------------------------------------ Warranty
def submit_warranty_claim(db: Session, customer: Customer, purchase: Purchase, issue: str) -> WarrantyClaim:
    product = db.get(Product, purchase.product_id)
    state = warranty_state(purchase)
    policy = get_policy(db, customer.organization_id)
    excerpts = knowledge_service.retrieve(db, customer.organization_id, f"warranty coverage {issue}",
                                          product_ids=[product.id], doc_types=["warranty_policy"], k=3, min_score=0.1)
    checks = [
        {"check": "Product has a warranty", "passed": purchase.warranty_expires_at is not None},
        {"check": "Within warranty period", "passed": state["status"] in ("ACTIVE", "EXPIRING_SOON"),
         "detail": f"Expires {purchase.warranty_expires_at}" if purchase.warranty_expires_at else "No warranty on record"},
        {"check": "Serial number on record", "passed": bool(purchase.serial_number)},
    ]
    eligible = all(c["passed"] for c in checks[:2])
    claim = WarrantyClaim(organization_id=customer.organization_id, customer_id=customer.id, purchase_id=purchase.id,
                          issue=issue.strip(), status=WarrantyStatus.SUBMITTED,
                          eligibility={"likely_eligible": eligible, "checks": checks, "warranty": state,
                                       "policy_excerpts": [{"title": e.title, "section": e.heading, "text": e.text[:600]}
                                                           for e in excerpts]})
    db.add(claim)
    db.flush()
    wf = wfs.start_workflow(db, customer.organization_id, WorkflowType.INBOUND, goal="Warranty claim",
                            customer_id=customer.id)
    wfs.record(db, wf, "warranty", "Basic eligibility check (rules)", TraceStatus.COMPLETED,
               ("Likely eligible" if eligible else "Likely NOT eligible") + f": warranty {state['status'].lower().replace('_', ' ')}",
               detail=claim.eligibility)
    if policy.warranty_auto_approve and eligible:
        claim.status = WarrantyStatus.APPROVED
        claim.resolution_note = "Approved automatically under your warranty policy."
        claim.decided_at = _now()
        wfs.record(db, wf, "warranty", "Auto-approve (configured policy)", TraceStatus.COMPLETED,
                   "Approved by configured policy", state=WorkflowState.COMPLETED)
    else:
        claim.status = WarrantyStatus.UNDER_REVIEW
        reason = ("Escalated because warranty decisions require human review (auto-approval is off). "
                  + ("Rules suggest the claim is within warranty." if eligible
                     else f"Rules suggest it may NOT be covered (warranty {state['status'].lower().replace('_', ' ')})."))
        approval_service.create(db, customer.organization_id, ApprovalType.WARRANTY_CLAIM,
                                title=f"Warranty claim: {product.name} — {customer.name}", reason=reason,
                                priority=Priority.HIGH, tier=PriorityTier.RED if not eligible else PriorityTier.YELLOW,
                                category="warranty_claim", recommended_action="Review the issue, eligibility checks and policy excerpts, then decide.",
                                warranty_claim_id=claim.id, customer_id=customer.id, workflow_id=wf.id)
        wfs.record(db, wf, "human", "Human review", TraceStatus.WAITING, "Waiting for the business owner's decision",
                   state=WorkflowState.AWAITING_APPROVAL)
    memory_service.remember(db, customer.organization_id, scope="customer", subject_id=customer.id, category="product",
                            key=f"warranty:{claim.id}", content=f"Warranty claim for {product.name}: {issue[:200]}",
                            source="warranty", replace=False)
    notify(db, customer.organization_id, customer_id=customer.id, kind="warranty",
           title=f"Warranty claim received for {product.name}", body="We'll review it and update you here.",
           link="/portal/warranty")
    db.flush()
    return claim


def decide_warranty(db: Session, claim: WarrantyClaim, status: WarrantyStatus, note: str, user_id) -> WarrantyClaim:
    if claim.status in (WarrantyStatus.COMPLETED, WarrantyStatus.REJECTED) and status != claim.status:
        raise InvalidStateError("This claim is already closed.")
    claim.status = status
    claim.resolution_note = note or claim.resolution_note
    claim.decided_by_user_id = user_id
    claim.decided_at = _now()
    if status in (WarrantyStatus.APPROVED, WarrantyStatus.REJECTED, WarrantyStatus.COMPLETED):
        approval_service.resolve_for(db, status=ApprovalStatus.APPROVED if status != WarrantyStatus.REJECTED
                                     else ApprovalStatus.REJECTED, user_id=user_id, note=note, warranty_claim_id=claim.id)
    product = db.get(Product, db.get(Purchase, claim.purchase_id).product_id)
    notify(db, claim.organization_id, customer_id=claim.customer_id, kind="warranty",
           title=f"Warranty claim for {product.name}: {status.value.replace('_', ' ').lower()}", body=note,
           link="/portal/warranty")
    return claim


# ------------------------------------------------------------------ Service / repair
def request_service(db: Session, customer: Customer, purchase: Purchase, *, issue: str, preferred_date: date | None,
                    preferred_time: str, contact_phone: str, contact_email: str) -> ServiceRequest:
    product = db.get(Product, purchase.product_id)
    req = ServiceRequest(organization_id=customer.organization_id, customer_id=customer.id, purchase_id=purchase.id,
                         issue=issue.strip(), preferred_date=preferred_date, preferred_time=preferred_time,
                         contact_phone=contact_phone or customer.phone, contact_email=contact_email or customer.email)
    db.add(req)
    db.flush()
    approval_service.create(db, customer.organization_id, ApprovalType.SERVICE_REQUEST,
                            title=f"Service request: {product.name} — {customer.name}",
                            reason="Escalated because service appointments must be confirmed by the business.",
                            priority=Priority.MEDIUM, category="service_request",
                            recommended_action=f"Confirm a time (customer prefers {preferred_date or 'any date'} {preferred_time}).",
                            service_request_id=req.id, customer_id=customer.id)
    notify(db, customer.organization_id, customer_id=customer.id, kind="service",
           title=f"Service request received for {product.name}", body="We'll confirm your appointment soon.",
           link="/portal/service")
    return req


_SERVICE_TRANSITIONS = {
    ServiceStatus.PENDING_CONFIRMATION: {ServiceStatus.CONFIRMED, ServiceStatus.RESCHEDULED, ServiceStatus.CANCELLED},
    ServiceStatus.CONFIRMED: {ServiceStatus.RESCHEDULED, ServiceStatus.IN_PROGRESS, ServiceStatus.CANCELLED, ServiceStatus.COMPLETED},
    ServiceStatus.RESCHEDULED: {ServiceStatus.CONFIRMED, ServiceStatus.RESCHEDULED, ServiceStatus.IN_PROGRESS, ServiceStatus.CANCELLED},
    ServiceStatus.IN_PROGRESS: {ServiceStatus.COMPLETED, ServiceStatus.CANCELLED},
    ServiceStatus.COMPLETED: set(),
    ServiceStatus.CANCELLED: set(),
}


def update_service(db: Session, req: ServiceRequest, status: ServiceStatus, *, scheduled_for: datetime | None = None,
                   note: str | None = None, user_id=None, by_customer: bool = False) -> ServiceRequest:
    if status != req.status and status not in _SERVICE_TRANSITIONS[req.status]:
        raise InvalidStateError(f"Cannot change a {req.status.value} request to {status.value}.")
    if by_customer and status != ServiceStatus.CANCELLED:
        raise InvalidStateError("Customers can only cancel a request.")
    if status in (ServiceStatus.CONFIRMED, ServiceStatus.RESCHEDULED) and not (scheduled_for or req.scheduled_for):
        raise InvalidStateError("Set an appointment time to confirm or reschedule.")
    req.status = status
    if scheduled_for:
        req.scheduled_for = scheduled_for
    if note is not None:
        req.owner_note = note
    purchase = db.get(Purchase, req.purchase_id)
    if status == ServiceStatus.IN_PROGRESS:
        purchase.status = PurchaseStatus.IN_SERVICE
    if status == ServiceStatus.COMPLETED:
        req.completed_at = _now()
        purchase.status = PurchaseStatus.ACTIVE
    if status != ServiceStatus.PENDING_CONFIRMATION:
        approval_service.resolve_for(db, status=ApprovalStatus.APPROVED if status != ServiceStatus.CANCELLED
                                     else ApprovalStatus.CANCELLED, user_id=user_id, service_request_id=req.id)
    product = db.get(Product, purchase.product_id)
    if not by_customer:
        when = f" for {req.scheduled_for:%Y-%m-%d %H:%M}" if req.scheduled_for and status in (
            ServiceStatus.CONFIRMED, ServiceStatus.RESCHEDULED) else ""
        notify(db, req.organization_id, customer_id=req.customer_id, kind="service",
               title=f"Service for {product.name}: {status.value.replace('_', ' ').lower()}{when}", body=note or "",
               link="/portal/service")
    return req
