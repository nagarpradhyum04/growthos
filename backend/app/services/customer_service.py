"""Customers, purchases and portal access."""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConflictError, InvalidStateError
from app.models import Contact, Customer, Lead, Notification, Product, Purchase
from app.models.enums import LeadStatus, TraceStatus, WorkflowState
from app.services import memory_service
from app.services import workflow_service as wfs
from app.services.common import get_owned
from app.services.suppression import hash_email, normalize_email


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    month = m + 1
    year = d.year + y
    days = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(d.day, days[month - 1]))


def create_customer(db: Session, organization_id: uuid.UUID, *, name: str, email: str, phone: str = "",
                    company: str = "", notes: str = "", lead_id=None, contact_id=None) -> Customer:
    email_hash = hash_email(email)
    if db.scalar(select(Customer.id).where(Customer.organization_id == organization_id,
                                           Customer.email_hash == email_hash)):
        raise ConflictError("A customer with this email already exists.")
    customer = Customer(organization_id=organization_id, name=name.strip(), email=normalize_email(email),
                        email_hash=email_hash, phone=phone.strip(), company=company.strip(), notes=notes.strip(),
                        lead_id=lead_id, contact_id=contact_id, preferences={"lifecycle_messages": True})
    db.add(customer)
    db.flush()
    memory_service.remember(db, organization_id, scope="customer", subject_id=customer.id, category="customer_info",
                            key="profile", content=f"{customer.name}" + (f" at {customer.company}" if customer.company else ""),
                            source="user")
    return customer


def convert_lead(db: Session, lead: Lead, *, product_id=None, purchased_at: date | None = None,
                 order_value: float | None = None, quantity: int = 1, serial_number: str = "") -> Customer:
    """The owner closes the deal: the lead's contact becomes a customer (optionally with a first purchase)."""
    contact = db.scalar(select(Contact).where(Contact.lead_id == lead.id).order_by(Contact.created_at))
    if contact is None or not contact.email:
        raise InvalidStateError("This lead has no contact email to convert.")
    if contact.suppressed:
        raise InvalidStateError("This contact opted out and cannot be converted.")
    existing = db.scalar(select(Customer).where(Customer.organization_id == lead.organization_id,
                                                Customer.email_hash == contact.email_hash))
    customer = existing or create_customer(db, lead.organization_id, name=contact.name or contact.email,
                                           email=contact.email, company=lead.company_name, lead_id=lead.id,
                                           contact_id=contact.id)
    # Carry the relationship context into the customer's memory.
    for entry in memory_service.recall(db, lead.organization_id, scope="lead", subject_id=lead.id, limit=20):
        memory_service.remember(db, lead.organization_id, scope="customer", subject_id=customer.id,
                                category=entry.category, key=f"lead:{entry.key}", content=entry.content,
                                source=entry.source, data=entry.data)
    purchase = None
    if product_id:
        purchase = add_purchase(db, customer, product_id=product_id, purchased_at=purchased_at or date.today(),
                                order_value=order_value, quantity=quantity, serial_number=serial_number)
    lead.status = LeadStatus.CONVERTED
    lead.last_activity_at = datetime.now(timezone.utc)
    wfs.advance_lead(db, lead, "human", "Convert to customer", TraceStatus.COMPLETED,
                     f"{customer.name} became a customer" + (" with a first purchase" if purchase else ""),
                     state=WorkflowState.COMPLETED)
    memory_service.remember(db, lead.organization_id, scope="campaign", subject_id=lead.campaign_id, category="result",
                            key=f"conversion:{lead.id}", content=f"{lead.company_name} converted to a customer",
                            source="user")
    db.flush()
    return customer


def add_purchase(db: Session, customer: Customer, *, product_id, purchased_at: date, order_value=None,
                 quantity: int = 1, serial_number: str = "") -> Purchase:
    product = get_owned(db, Product, product_id, customer.organization_id)
    purchase = Purchase(organization_id=customer.organization_id, customer_id=customer.id, product_id=product.id,
                        purchased_at=purchased_at, quantity=quantity, order_value=order_value,
                        serial_number=serial_number.strip(),
                        warranty_expires_at=add_months(purchased_at, product.warranty_months)
                        if product.warranty_months else None)
    db.add(purchase)
    db.flush()
    memory_service.remember(db, customer.organization_id, scope="customer", subject_id=customer.id, category="product",
                            key=f"purchase:{purchase.id}", content=f"Bought {quantity} × {product.name} on {purchased_at}"
                            + (f"; warranty until {purchase.warranty_expires_at}" if purchase.warranty_expires_at else ""),
                            source="user")
    db.add(Notification(organization_id=customer.organization_id, customer_id=customer.id, kind="purchase",
                        title=f"{product.name} added to your products", link="/portal/products"))
    db.flush()
    return purchase


def warranty_state(purchase: Purchase, today: date | None = None) -> dict:
    """Deterministic warranty status from stored dates. Never guessed."""
    today = today or date.today()
    if purchase.warranty_expires_at is None:
        return {"status": "NO_WARRANTY", "days_left": None}
    days = (purchase.warranty_expires_at - today).days
    if days < 0:
        return {"status": "EXPIRED", "days_left": days}
    return {"status": "EXPIRING_SOON" if days <= 30 else "ACTIVE", "days_left": days}
