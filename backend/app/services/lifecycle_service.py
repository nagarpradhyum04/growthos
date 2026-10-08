"""Customer lifecycle follow-ups (Follow-up Agent beyond sales).

Events: setup_help, post_purchase_checkin (days after purchase), warranty_expiry_notice (days before expiry),
post_service (days after a completed service). Before anything is generated the backend checks:
policy switch, customer preference, suppression, frequency limit, and idempotency (one message per event).
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AgentFailedError
from app.models import BusinessProfile, Customer, LifecycleEvent, Product, Purchase, ServiceRequest
from app.models.enums import MessageSender, ServiceStatus, TraceStatus, WorkflowState, WorkflowType
from app.services import memory_service
from app.services import workflow_service as wfs
from app.services.container import Container
from app.services.customer_care import _add_message, get_conversation, notify
from app.services.llm.run_logger import RunContext
from app.services.policy import get_policy
from app.services.suppression import is_suppressed


def due_events(db: Session, organization_id, today: date) -> list[dict]:
    rules = get_policy(db, organization_id).lifecycle_rules or {}
    events = []
    rows = db.execute(select(Purchase, Product, Customer)
                      .join(Product, Product.id == Purchase.product_id)
                      .join(Customer, Customer.id == Purchase.customer_id)
                      .where(Purchase.organization_id == organization_id)).all()
    for pu, product, customer in rows:
        age = (today - pu.purchased_at).days
        for event, key in (("setup_help", "setup_help_days"), ("post_purchase_checkin", "post_purchase_checkin_days")):
            days = rules.get(key)
            # Only within a 14-day window after the trigger so old purchases don't get a burst of messages.
            if days is not None and days <= age <= days + 14:
                events.append({"event": event, "customer": customer, "product": product, "purchase": pu,
                               "dedupe": f"{event}:{pu.id}"})
        notice = rules.get("warranty_expiry_notice_days")
        if notice is not None and pu.warranty_expires_at and 0 <= (pu.warranty_expires_at - today).days <= notice:
            events.append({"event": "warranty_expiry_notice", "customer": customer, "product": product, "purchase": pu,
                           "dedupe": f"warranty_expiry_notice:{pu.id}"})
    post = rules.get("post_service_days")
    if post is not None:
        services = db.execute(select(ServiceRequest, Purchase, Product, Customer)
                              .join(Purchase, Purchase.id == ServiceRequest.purchase_id)
                              .join(Product, Product.id == Purchase.product_id)
                              .join(Customer, Customer.id == ServiceRequest.customer_id)
                              .where(ServiceRequest.organization_id == organization_id,
                                     ServiceRequest.status == ServiceStatus.COMPLETED)).all()
        for req, pu, product, customer in services:
            if req.completed_at and post <= (today - req.completed_at.date()).days <= post + 14:
                events.append({"event": "post_service", "customer": customer, "product": product, "purchase": pu,
                               "dedupe": f"post_service:{req.id}"})
    return events


def _blocked_reason(db: Session, customer: Customer, policy, now: datetime) -> str | None:
    if not policy.lifecycle_enabled:
        return "Lifecycle follow-ups are turned off in your automation rules"
    if not (customer.preferences or {}).get("lifecycle_messages", True):
        return "Customer opted out of lifecycle messages"
    if is_suppressed(db, customer.organization_id, customer.email_hash):
        return "Customer is suppressed (unsubscribed / Forget Me)"
    recent = db.scalar(select(func.count(LifecycleEvent.id)).where(
        LifecycleEvent.customer_id == customer.id, LifecycleEvent.status == "SENT",
        LifecycleEvent.created_at >= now - timedelta(days=7))) or 0
    if recent >= policy.lifecycle_max_per_7d:
        return f"Frequency limit: {recent} lifecycle message(s) in the last 7 days (max {policy.lifecycle_max_per_7d})"
    return None


def process_lifecycle(db: Session, container: Container, organization_id, today: date | None = None) -> dict:
    today = today or date.today()
    now = datetime.now(timezone.utc)
    policy = get_policy(db, organization_id)
    profile = db.scalar(select(BusinessProfile).where(BusinessProfile.organization_id == organization_id))
    outcomes = {"sent": 0, "blocked": 0, "deferred": 0, "skipped_existing": 0, "failed": 0}
    for ev in due_events(db, organization_id, today):
        if db.scalar(select(LifecycleEvent.id).where(LifecycleEvent.dedupe_key == ev["dedupe"])):
            outcomes["skipped_existing"] += 1
            continue
        customer, product, purchase = ev["customer"], ev["product"], ev["purchase"]
        blocked = _blocked_reason(db, customer, policy, now)
        if blocked and blocked.startswith("Frequency"):
            # Deferred, not dropped: retried on a later run once the window allows. No trace spam per tick.
            outcomes["deferred"] = outcomes.get("deferred", 0) + 1
            continue
        wf = wfs.start_workflow(db, organization_id, WorkflowType.LIFECYCLE, goal=f"Lifecycle: {ev['event']}",
                                customer_id=customer.id)
        if blocked:
            wfs.record(db, wf, "safety", "Lifecycle policy check", TraceStatus.BLOCKED, blocked, state=WorkflowState.BLOCKED)
            # Opt-outs / disabled rules are permanent for this event.
            db.add(LifecycleEvent(organization_id=organization_id, customer_id=customer.id, event_type=ev["event"],
                                  dedupe_key=ev["dedupe"], status="BLOCKED", reason=blocked))
            outcomes["blocked"] += 1
            db.commit()
            continue
        wfs.record(db, wf, "safety", "Lifecycle policy check", TraceStatus.COMPLETED,
                   "Allowed: preferences, suppression and frequency limits respected")
        context = {"event": ev["event"], "customer": {"name": customer.name, "company": customer.company},
                   "product": {"name": product.name}, "purchased_at": str(purchase.purchased_at),
                   "warranty_expires_at": str(purchase.warranty_expires_at) if purchase.warranty_expires_at else None,
                   "business_profile": {"company_name": profile.company_name if profile else ""},
                   "shared_memory": memory_service.customer_context(db, customer)["memory"]}
        try:
            out = container.lifecycle_agent().run(context, RunContext(organization_id=organization_id)).output
        except AgentFailedError as exc:
            wfs.record(db, wf, "followup", "Write lifecycle message", TraceStatus.FAILED, exc.message, state=WorkflowState.FAILED)
            outcomes["failed"] += 1
            db.commit()
            continue
        conv = get_conversation(db, customer, "business")
        msg = _add_message(db, conv, MessageSender.AI, f"{out.subject}\n\n{out.body}", handled_automatically=True,
                           analysis={"lifecycle_event": ev["event"]})
        notify(db, organization_id, customer_id=customer.id, kind="lifecycle", title=out.subject, body=out.body[:300],
               link="/portal/conversations")
        try:
            db.add(LifecycleEvent(organization_id=organization_id, customer_id=customer.id, event_type=ev["event"],
                                  dedupe_key=ev["dedupe"], status="SENT", message_id=msg.id,
                                  reason=f"{ev['event']} for {product.name}"))
            wfs.record(db, wf, "followup", "Send lifecycle message", TraceStatus.COMPLETED,
                       f"“{out.subject}” delivered to the customer portal", state=WorkflowState.COMPLETED)
            memory_service.remember(db, organization_id, scope="customer", subject_id=customer.id,
                                    category="conversation", key=f"lifecycle:{ev['dedupe']}",
                                    content=f"Lifecycle message sent: {out.subject}", source="followup")
            db.commit()
            outcomes["sent"] += 1
        except IntegrityError:
            db.rollback()  # another worker sent it first
            outcomes["skipped_existing"] += 1
    return outcomes
