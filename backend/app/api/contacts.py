import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, current_user
from app.db import get_db
from app.models import Contact
from app.models.enums import SuppressionReason
from app.schemas import ContactOut
from app.services.common import get_owned
from app.services.suppression import forget_contact, suppress_contact

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.post("/{contact_id}/forget", response_model=ContactOut)
def forget(contact_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Forget Me: suppress permanently, cancel everything pending, erase personal data."""
    contact = get_owned(db, Contact, contact_id, cu.org_id, for_update=True)
    forget_contact(db, contact, source=f"user:{cu.id}")
    db.commit()
    return contact


@router.post("/{contact_id}/unsubscribe", response_model=ContactOut)
def unsubscribe(contact_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    contact = get_owned(db, Contact, contact_id, cu.org_id, for_update=True)
    suppress_contact(db, contact, SuppressionReason.UNSUBSCRIBED, source=f"user:{cu.id}")
    db.commit()
    return contact
