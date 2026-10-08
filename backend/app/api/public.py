"""Public (unauthenticated) endpoints reachable from links inside emails."""
import uuid
from html import escape

import jwt
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Contact
from app.models.enums import SuppressionReason
from app.security import decode_token
from app.services.suppression import suppress_contact

router = APIRouter(prefix="/public", tags=["public"])


def _page(message: str, form_token: str | None = None) -> HTMLResponse:
    form = ""
    if form_token:
        form = (f'<form method="post" action="/public/unsubscribe?token={escape(form_token)}">'
                '<button type="submit">Unsubscribe me</button></form>')
    return HTMLResponse(f"<!doctype html><html><body style='font-family:sans-serif;max-width:480px;margin:4rem auto'>"
                        f"<p>{escape(message)}</p>{form}</body></html>")


def _contact_from_token(db: Session, token: str) -> Contact | None:
    try:
        payload = decode_token(token, "unsubscribe")
        contact = db.get(Contact, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    if contact is None or str(contact.organization_id) != payload.get("org"):
        return None
    return contact


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(token: str, db: Session = Depends(get_db)):
    # GET only shows a confirmation button: link scanners must not unsubscribe people by prefetching.
    if _contact_from_token(db, token) is None:
        return _page("This unsubscribe link is invalid.")
    return _page("Click below to stop receiving emails from us.", form_token=token)


@router.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str, db: Session = Depends(get_db)):
    contact = _contact_from_token(db, token)
    if contact is None:
        return _page("This unsubscribe link is invalid.")
    if not contact.suppressed:
        suppress_contact(db, contact, SuppressionReason.UNSUBSCRIBED, source="unsubscribe_link")
        db.commit()
    return _page("You have been unsubscribed. You will not receive further emails from us.")
