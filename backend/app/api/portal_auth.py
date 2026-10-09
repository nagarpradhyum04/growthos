"""Public customer-portal sign-in endpoints (Business ID + email + one-time code)."""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import container
from app.db import get_db
from app.services import portal_access
from app.services.container import Container

router = APIRouter(prefix="/portal-auth", tags=["customer portal"])


class AccessIn(BaseModel):
    business_id: str = Field(min_length=3, max_length=20)
    email: EmailStr


class VerifyIn(BaseModel):
    request_id: uuid.UUID
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


@router.post("/request")
def request_access(body: AccessIn, db: Session = Depends(get_db), c: Container = Depends(container)):
    r = portal_access.request_access(db, body.business_id, str(body.email), c)
    out = {"request_id": str(r.request_id), "message": r.message}
    if r.dev_code:
        out["dev_code"] = r.dev_code  # local demo only (mock email provider)
    return out


@router.post("/verify")
def verify(body: VerifyIn, db: Session = Depends(get_db)):
    token, customer = portal_access.verify_code(db, body.request_id, body.code)
    return {"access_token": token, "token_type": "bearer", "role": "customer", "name": customer.name}
