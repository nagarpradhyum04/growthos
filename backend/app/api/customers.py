"""Business-owner customer management (customers, purchases, portal access, conversations)."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, container, current_user
from app.db import get_db
from app.models import Conversation, Customer, Lead, Message, Product, Purchase, ServiceRequest, User, WarrantyClaim
from app.services import customer_care, customer_service, memory_service
from app.services.common import get_owned
from app.services.container import Container

router = APIRouter(tags=["customers"])


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str = Field(default="", max_length=64)
    company: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=5000)


class PurchaseIn(BaseModel):
    product_id: uuid.UUID
    purchased_at: date
    quantity: int = Field(default=1, ge=1, le=100000)
    order_value: float | None = Field(default=None, ge=0)
    serial_number: str = Field(default="", max_length=100)


class ConvertIn(BaseModel):
    product_id: uuid.UUID | None = None
    purchased_at: date | None = None
    quantity: int = Field(default=1, ge=1)
    order_value: float | None = None
    serial_number: str = ""


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


def purchase_dict(pu: Purchase, product: Product) -> dict:
    return {"id": str(pu.id), "product_id": str(product.id), "product_name": product.name, "sku": product.sku,
            "category": product.category, "purchased_at": pu.purchased_at, "warranty_expires_at": pu.warranty_expires_at,
            "warranty": customer_service.warranty_state(pu), "serial_number": pu.serial_number,
            "quantity": pu.quantity, "order_value": float(pu.order_value) if pu.order_value is not None else None,
            "status": pu.status.value}


def customer_dict(db: Session, c: Customer, detail: bool = False) -> dict:
    # "portal_access": has this customer signed in to the portal at least once (Business ID + email code)?
    has_portal = db.scalar(select(User.id).where(User.customer_id == c.id)) is not None
    data = {"id": str(c.id), "name": c.name, "email": c.email, "phone": c.phone, "company": c.company,
            "status": c.status.value, "lead_id": str(c.lead_id) if c.lead_id else None, "notes": c.notes,
            "preferences": c.preferences, "portal_access": has_portal, "created_at": c.created_at}
    if detail:
        data["purchases"] = [purchase_dict(pu, p) for pu, p in customer_care.customer_products(db, c)]
        data["warranty_claims"] = [{"id": str(w.id), "issue": w.issue, "status": w.status.value, "created_at": w.created_at}
                                   for w in db.scalars(select(WarrantyClaim).where(WarrantyClaim.customer_id == c.id))]
        data["service_requests"] = [{"id": str(s.id), "issue": s.issue, "status": s.status.value,
                                     "scheduled_for": s.scheduled_for}
                                    for s in db.scalars(select(ServiceRequest).where(ServiceRequest.customer_id == c.id))]
        msgs = db.execute(select(Message, Conversation.channel).join(Conversation, Conversation.id == Message.conversation_id)
                          .where(Message.customer_id == c.id).order_by(Message.created_at)).all()
        data["messages"] = [message_dict(m, ch) for m, ch in msgs]
        data["memory"] = [{"category": e.category, "key": e.key, "content": e.content, "source": e.source,
                           "updated_at": e.updated_at}
                          for e in memory_service.recall(db, c.organization_id, scope="customer", subject_id=c.id, limit=50)]
    return data


def message_dict(m: Message, channel: str) -> dict:
    """Owner view: includes Email Intelligence analysis."""
    return {"id": str(m.id), "channel": channel, "sender": m.sender.value, "body": m.body,
            "tier": m.tier.value if m.tier else None, "intents": m.intents, "analysis": m.analysis,
            "sources": m.sources, "handled_automatically": m.handled_automatically, "created_at": m.created_at,
            "customer_id": str(m.customer_id)}


@router.get("/customers")
def list_customers(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Customer).where(Customer.organization_id == cu.org_id).order_by(Customer.created_at.desc()))
    return [customer_dict(db, c) for c in rows]


@router.post("/customers", status_code=201)
def create_customer(body: CustomerIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    c = customer_service.create_customer(db, cu.org_id, **body.model_dump())
    db.commit()
    return customer_dict(db, c, detail=True)


@router.get("/customers/{customer_id}")
def get_customer(customer_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return customer_dict(db, get_owned(db, Customer, customer_id, cu.org_id), detail=True)


@router.post("/customers/{customer_id}/purchases", status_code=201)
def add_purchase(customer_id: uuid.UUID, body: PurchaseIn, cu: CurrentUser = Depends(current_user),
                 db: Session = Depends(get_db)):
    c = get_owned(db, Customer, customer_id, cu.org_id)
    pu = customer_service.add_purchase(db, c, **body.model_dump())
    db.commit()
    return purchase_dict(pu, db.get(Product, pu.product_id))


@router.post("/customers/{customer_id}/messages", status_code=201)
def reply_to_customer(customer_id: uuid.UUID, body: MessageIn, cu: CurrentUser = Depends(current_user),
                      db: Session = Depends(get_db)):
    c = get_owned(db, Customer, customer_id, cu.org_id)
    m = customer_care.business_reply(db, c, body.body, cu.id)
    db.commit()
    return message_dict(m, "business")


@router.post("/leads/{lead_id}/convert", status_code=201)
def convert_lead(lead_id: uuid.UUID, body: ConvertIn, cu: CurrentUser = Depends(current_user),
                 db: Session = Depends(get_db)):
    """Owner closes the deal: the lead becomes a customer (with an optional first purchase)."""
    lead = get_owned(db, Lead, lead_id, cu.org_id)
    if body.product_id:
        get_owned(db, Product, body.product_id, cu.org_id)
    c = customer_service.convert_lead(db, lead, **body.model_dump())
    db.commit()
    return customer_dict(db, c, detail=True)


@router.get("/inbox")
def inbox(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Customer messages with Email Intelligence analysis (newest first)."""
    rows = db.execute(select(Message, Conversation.channel, Customer.name)
                      .join(Conversation, Conversation.id == Message.conversation_id)
                      .join(Customer, Customer.id == Message.customer_id)
                      .where(Message.organization_id == cu.org_id).order_by(Message.created_at.desc()).limit(300)).all()
    return [{**message_dict(m, ch), "customer_name": name} for m, ch, name in rows]
