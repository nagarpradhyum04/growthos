"""Provider webhooks: inbound replies and delivery status. Protected by a shared secret."""
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import NotFoundError
from app.schemas import DeliveryWebhook, InboundEmailWebhook
from app.services import email_service, jobs, reply_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def verify_secret(x_webhook_secret: str = Header(default="")) -> None:
    expected = get_settings().webhook_secret
    if not expected or not hmac.compare_digest(x_webhook_secret, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


@router.post("/inbound-email", dependencies=[Depends(verify_secret)])
def inbound_email(body: InboundEmailWebhook, db: Session = Depends(get_db)):
    try:
        reply, created = reply_service.record_reply(
            db, body.organization_id, subject=body.subject, body=body.body, email_id=body.in_reply_to_email_id,
            from_address=str(body.from_address), received_at=body.received_at, external_id=body.message_id,
        )
    except NotFoundError:
        # Acknowledge so the provider doesn't retry forever; nothing to match.
        return {"status": "ignored", "reason": "no matching sent email"}
    db.commit()
    if created and reply.analyzed_at is None:
        jobs.enqueue(db, "analyze_reply", {"reply_id": str(reply.id), "lead_id": str(reply.lead_id),
                                           "contact_id": str(reply.contact_id)},
                     organization_id=reply.organization_id, dedupe_key=f"analyze_reply:{reply.id}")
        db.commit()
    return {"status": "recorded" if created else "duplicate", "reply_id": str(reply.id)}


@router.post("/email-status", dependencies=[Depends(verify_secret)])
def email_status(body: DeliveryWebhook, db: Session = Depends(get_db)):
    if body.event == "delivered":
        email = email_service.mark_delivered(db, body.provider_message_id)
        db.commit()
        return {"status": "updated" if email else "ignored"}
    return {"status": "ignored"}
