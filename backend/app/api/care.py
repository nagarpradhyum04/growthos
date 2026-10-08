"""Owner-side warranty claims, service requests, lifecycle runs and owner notifications."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, container, current_user
from app.db import get_db
from app.models import Customer, Notification, Product, Purchase, ServiceRequest, WarrantyClaim
from app.models.enums import ServiceStatus, WarrantyStatus
from app.services import customer_care, lifecycle_service
from app.services.common import get_owned
from app.services.container import Container

router = APIRouter(tags=["customer care"])


class WarrantyDecision(BaseModel):
    status: WarrantyStatus
    note: str = Field(default="", max_length=3000)


class ServiceUpdate(BaseModel):
    status: ServiceStatus
    scheduled_for: datetime | None = None
    note: str | None = Field(default=None, max_length=3000)


def _context(db: Session, customer_id, purchase_id) -> dict:
    c = db.get(Customer, customer_id)
    pu = db.get(Purchase, purchase_id)
    p = db.get(Product, pu.product_id)
    return {"customer_id": str(c.id), "customer_name": c.name, "purchase_id": str(pu.id), "product_name": p.name,
            "serial_number": pu.serial_number, "purchased_at": pu.purchased_at, "warranty_expires_at": pu.warranty_expires_at}


def claim_dict(db: Session, w: WarrantyClaim) -> dict:
    return {"id": str(w.id), "issue": w.issue, "status": w.status.value, "eligibility": w.eligibility,
            "resolution_note": w.resolution_note, "created_at": w.created_at, "decided_at": w.decided_at,
            **_context(db, w.customer_id, w.purchase_id)}


def service_dict(db: Session, s: ServiceRequest) -> dict:
    return {"id": str(s.id), "issue": s.issue, "status": s.status.value, "preferred_date": s.preferred_date,
            "preferred_time": s.preferred_time, "contact_phone": s.contact_phone, "contact_email": s.contact_email,
            "scheduled_for": s.scheduled_for, "owner_note": s.owner_note, "created_at": s.created_at,
            "completed_at": s.completed_at, **_context(db, s.customer_id, s.purchase_id)}


@router.get("/warranty-claims")
def list_claims(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return [claim_dict(db, w) for w in db.scalars(select(WarrantyClaim).where(WarrantyClaim.organization_id == cu.org_id)
                                                  .order_by(WarrantyClaim.created_at.desc()))]


@router.patch("/warranty-claims/{claim_id}")
def decide_claim(claim_id: uuid.UUID, body: WarrantyDecision, cu: CurrentUser = Depends(current_user),
                 db: Session = Depends(get_db)):
    w = get_owned(db, WarrantyClaim, claim_id, cu.org_id, for_update=True)
    customer_care.decide_warranty(db, w, body.status, body.note, cu.id)
    db.commit()
    return claim_dict(db, w)


@router.get("/service-requests")
def list_services(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return [service_dict(db, s) for s in db.scalars(select(ServiceRequest).where(ServiceRequest.organization_id == cu.org_id)
                                                    .order_by(ServiceRequest.created_at.desc()))]


@router.patch("/service-requests/{request_id}")
def update_service(request_id: uuid.UUID, body: ServiceUpdate, cu: CurrentUser = Depends(current_user),
                   db: Session = Depends(get_db)):
    s = get_owned(db, ServiceRequest, request_id, cu.org_id, for_update=True)
    customer_care.update_service(db, s, body.status, scheduled_for=body.scheduled_for, note=body.note, user_id=cu.id)
    db.commit()
    return service_dict(db, s)


@router.post("/lifecycle/run")
def run_lifecycle(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db), c: Container = Depends(container)):
    """Process due lifecycle follow-ups now (the worker also runs this on every tick)."""
    return lifecycle_service.process_lifecycle(db, c, cu.org_id)


@router.get("/notifications")
def owner_notifications(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.organization_id == cu.org_id,
                                                 Notification.customer_id.is_(None))
                      .order_by(Notification.created_at.desc()).limit(50))
    return [{"id": str(n.id), "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
             "read": n.read_at is not None, "created_at": n.created_at} for n in rows]


@router.post("/notifications/read-all", status_code=204)
def owner_read_all(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.organization_id == cu.org_id,
                                                   Notification.customer_id.is_(None), Notification.read_at.is_(None))):
        n.read_at = datetime.now(timezone.utc)
    db.commit()
