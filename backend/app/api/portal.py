"""Customer portal API.

Every query is scoped to the customer bound to the token (current_customer). Responses are built
explicitly so internal data (lead scores, tiers, intents, agent reasoning, campaigns, other customers)
can never leak through.
"""
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentCustomer, container, current_customer
from app.db import get_db
from app.models import (
    BusinessProfile,
    Conversation,
    KnowledgeDocument,
    Message,
    Notification,
    Organization,
    Product,
    Purchase,
    ServiceRequest,
    WarrantyClaim,
)
from app.models.enums import ServiceStatus
from app.services import customer_care
from app.services.container import Container
from app.services.customer_service import warranty_state

router = APIRouter(prefix="/portal", tags=["customer portal"])


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    purchase_id: uuid.UUID | None = None


class WarrantyIn(BaseModel):
    purchase_id: uuid.UUID
    issue: str = Field(min_length=5, max_length=5000)


class ServiceIn(BaseModel):
    purchase_id: uuid.UUID
    issue: str = Field(min_length=5, max_length=5000)
    preferred_date: date | None = None
    preferred_time: str = Field(default="", max_length=64)
    contact_phone: str = Field(default="", max_length=64)
    contact_email: str = Field(default="", max_length=320)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class PreferencesIn(BaseModel):
    lifecycle_messages: bool


def _own_purchase(db: Session, cc: CurrentCustomer, purchase_id: uuid.UUID) -> Purchase:
    pu = db.scalar(select(Purchase).where(Purchase.id == purchase_id, Purchase.customer_id == cc.customer.id))
    if pu is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return pu


def _product_card(pu: Purchase, p: Product) -> dict:
    return {"purchase_id": str(pu.id), "product_name": p.name, "category": p.category, "description": p.description,
            "purchased_at": pu.purchased_at, "serial_number": pu.serial_number, "quantity": pu.quantity,
            "status": pu.status.value, "warranty_expires_at": pu.warranty_expires_at, "warranty": warranty_state(pu),
            "warranty_months": p.warranty_months}


def _public_message(m: Message) -> dict:
    # Only what the customer may see: who wrote it, text, and documentation sources for AI answers.
    return {"id": str(m.id), "sender": m.sender.value, "body": m.body, "sources": m.sources if m.sender.value == "ai" else [],
            "created_at": m.created_at}


def _claim(db: Session, w: WarrantyClaim) -> dict:
    pu = db.get(Purchase, w.purchase_id)
    return {"id": str(w.id), "product_name": db.get(Product, pu.product_id).name, "purchase_id": str(pu.id),
            "issue": w.issue, "status": w.status.value, "resolution_note": w.resolution_note,
            "created_at": w.created_at, "updated_at": w.updated_at}


def _service(db: Session, s: ServiceRequest) -> dict:
    pu = db.get(Purchase, s.purchase_id)
    return {"id": str(s.id), "product_name": db.get(Product, pu.product_id).name, "purchase_id": str(pu.id),
            "issue": s.issue, "status": s.status.value, "preferred_date": s.preferred_date,
            "preferred_time": s.preferred_time, "scheduled_for": s.scheduled_for, "note": s.owner_note,
            "created_at": s.created_at}


@router.get("/me")
def me(cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    org = db.get(Organization, cc.org_id)
    profile = db.scalar(select(BusinessProfile).where(BusinessProfile.organization_id == cc.org_id))
    c = cc.customer
    return {"customer": {"name": c.name, "email": c.email, "company": c.company, "phone": c.phone,
                         "preferences": c.preferences},
            "business": {"name": (profile.company_name if profile and profile.company_name else org.name),
                         "website": profile.website if profile else ""}}


@router.patch("/preferences")
def preferences(body: PreferencesIn, cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    cc.customer.preferences = {**(cc.customer.preferences or {}), "lifecycle_messages": body.lifecycle_messages}
    db.commit()
    return cc.customer.preferences


@router.get("/products")
def products(cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    return [_product_card(pu, p) for pu, p in customer_care.customer_products(db, cc.customer)]


@router.get("/products/{purchase_id}")
def product_detail(purchase_id: uuid.UUID, cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    pu = _own_purchase(db, cc, purchase_id)
    p = db.get(Product, pu.product_id)
    docs = db.scalars(select(KnowledgeDocument).where(
        KnowledgeDocument.organization_id == cc.org_id,
        or_(KnowledgeDocument.product_id == p.id, KnowledgeDocument.product_id.is_(None)))
        .order_by(KnowledgeDocument.title)).all()
    return {**_product_card(pu, p),
            "documents": [{"id": str(d.id), "title": d.title, "doc_type": d.doc_type, "content": d.content} for d in docs],
            "warranty_claims": [_claim(db, w) for w in db.scalars(select(WarrantyClaim).where(WarrantyClaim.purchase_id == pu.id))],
            "service_requests": [_service(db, s) for s in db.scalars(select(ServiceRequest).where(ServiceRequest.purchase_id == pu.id))]}


@router.post("/support/ask")
def ask(body: AskIn, cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db),
        c: Container = Depends(container)):
    purchase = _own_purchase(db, cc, body.purchase_id) if body.purchase_id else None
    q, a, result = customer_care.support_chat(db, cc.customer, purchase, body.question, c)
    db.commit()
    return {"question": _public_message(q), "answer": _public_message(a), "answerable": result["answerable"],
            "can_escalate": not result["answerable"] or result["escalate"]}


@router.get("/support/history")
def support_history(purchase_id: uuid.UUID | None = None, cc: CurrentCustomer = Depends(current_customer),
                    db: Session = Depends(get_db)):
    if purchase_id:
        _own_purchase(db, cc, purchase_id)
    conv = db.scalar(select(Conversation).where(Conversation.customer_id == cc.customer.id,
                                                Conversation.channel == "support_ai",
                                                Conversation.purchase_id == purchase_id))
    if conv is None:
        return []
    return [_public_message(m) for m in db.scalars(select(Message).where(Message.conversation_id == conv.id)
                                                   .order_by(Message.created_at))]


@router.get("/warranty")
def list_warranty(cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    return [_claim(db, w) for w in db.scalars(select(WarrantyClaim).where(WarrantyClaim.customer_id == cc.customer.id)
                                              .order_by(WarrantyClaim.created_at.desc()))]


@router.post("/warranty", status_code=201)
def submit_warranty(body: WarrantyIn, cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    pu = _own_purchase(db, cc, body.purchase_id)
    w = customer_care.submit_warranty_claim(db, cc.customer, pu, body.issue)
    db.commit()
    return _claim(db, w)


@router.get("/service")
def list_service(cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    return [_service(db, s) for s in db.scalars(select(ServiceRequest).where(ServiceRequest.customer_id == cc.customer.id)
                                                .order_by(ServiceRequest.created_at.desc()))]


@router.post("/service", status_code=201)
def request_service(body: ServiceIn, cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    pu = _own_purchase(db, cc, body.purchase_id)
    s = customer_care.request_service(db, cc.customer, pu, **body.model_dump(exclude={"purchase_id"}))
    db.commit()
    return _service(db, s)


@router.post("/service/{request_id}/cancel")
def cancel_service(request_id: uuid.UUID, cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    s = db.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id,
                                               ServiceRequest.customer_id == cc.customer.id).with_for_update())
    if s is None:
        raise HTTPException(status_code=404, detail="Request not found")
    customer_care.update_service(db, s, ServiceStatus.CANCELLED, note="Cancelled by customer", by_customer=True)
    db.commit()
    return _service(db, s)


@router.get("/appointments")
def appointments(cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    rows = db.scalars(select(ServiceRequest).where(
        ServiceRequest.customer_id == cc.customer.id, ServiceRequest.scheduled_for.is_not(None),
        ServiceRequest.status.in_([ServiceStatus.CONFIRMED, ServiceStatus.RESCHEDULED, ServiceStatus.IN_PROGRESS,
                                   ServiceStatus.COMPLETED])).order_by(ServiceRequest.scheduled_for))
    return [_service(db, s) for s in rows]


@router.get("/conversations")
def conversation(cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    conv = db.scalar(select(Conversation).where(Conversation.customer_id == cc.customer.id,
                                                Conversation.channel == "business"))
    if conv is None:
        return []
    return [_public_message(m) for m in db.scalars(select(Message).where(Message.conversation_id == conv.id)
                                                   .order_by(Message.created_at))]


@router.post("/conversations", status_code=201)
def send_message(body: MessageIn, cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db),
                 c: Container = Depends(container)):
    customer_care.customer_message(db, cc.customer, body.body, c)
    db.commit()
    return conversation(cc, db)


@router.get("/notifications")
def notifications(cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.customer_id == cc.customer.id)
                      .order_by(Notification.created_at.desc()).limit(50))
    return [{"id": str(n.id), "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
             "read": n.read_at is not None, "created_at": n.created_at} for n in rows]


@router.post("/notifications/read-all", status_code=204)
def read_all(cc: CurrentCustomer = Depends(current_customer), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.customer_id == cc.customer.id,
                                                   Notification.read_at.is_(None))):
        n.read_at = datetime.now(timezone.utc)
    db.commit()
