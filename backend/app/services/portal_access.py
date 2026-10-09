"""Customer portal sign-in: Business ID + email -> Access Agent check -> one-time code -> session.

The Access Agent is deliberately rule-based (no LLM): granting access to customer data is a security
decision. It checks that the Business ID exists, the email belongs to a registered customer of that
business, the customer is not suppressed/forgotten, and the request rate is reasonable. Responses never
reveal whether an email is registered; the code is only sent to registered customers.
"""
import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import GrowthOSError
from app.models import Customer, Organization, PortalAccessRequest, User
from app.models.enums import TraceStatus, UserRole, WorkflowState, WorkflowType
from app.security import create_access_token, hash_password
from app.services import workflow_service as wfs
from app.services.container import Container
from app.services.email import EmailSendError, OutgoingEmail
from app.services.suppression import hash_email, is_suppressed

logger = logging.getLogger(__name__)
MAX_REQUESTS_PER_HOUR = 5
MAX_CODE_ATTEMPTS = 5
GENERIC_MESSAGE = ("If this email is registered with this business, a sign-in code has been sent to it. "
                   "Codes expire in {ttl} minutes.")


class PortalAuthError(GrowthOSError):
    status_code = 401
    code = "portal_auth_failed"


def _hash_code(request_id: uuid.UUID, code: str) -> str:
    return hmac.new(get_settings().jwt_secret.encode(), f"{request_id}:{code}".encode(), hashlib.sha256).hexdigest()


@dataclass
class AccessRequestResult:
    request_id: uuid.UUID
    message: str
    verified: bool
    dev_code: str | None = None  # only with the mock email provider (local demo), never in production


def request_access(db: Session, business_code: str, email: str, container: Container) -> AccessRequestResult:
    settings = container.settings
    code_in = business_code.strip().upper()
    email_hash = hash_email(email)
    org = db.scalar(select(Organization).where(Organization.business_code == code_in))
    req = PortalAccessRequest(organization_id=org.id if org else None, business_code=code_in[:20],
                              email_hash=email_hash, status="REJECTED")
    db.add(req)
    db.flush()

    # --- Access Agent checks (rules) ---
    checks: list[tuple[str, bool]] = []
    customer = None
    recent = db.scalar(select(func.count(PortalAccessRequest.id)).where(
        PortalAccessRequest.email_hash == email_hash,
        PortalAccessRequest.created_at >= datetime.now(timezone.utc) - timedelta(hours=1))) or 0
    checks.append(("Request rate within limit", recent <= MAX_REQUESTS_PER_HOUR))
    checks.append(("Business ID exists", org is not None))
    if org is not None:
        customer = db.scalar(select(Customer).where(Customer.organization_id == org.id,
                                                    Customer.email_hash == email_hash))
        checks.append(("Email is a registered customer of this business", customer is not None))
        if customer is not None:
            checks.append(("Customer has not opted out / been forgotten",
                           not is_suppressed(db, org.id, email_hash)))
    failed = [name for name, ok in checks if not ok]
    req.reason = "All checks passed" if not failed else "Failed: " + "; ".join(failed)

    if org is not None:  # the owner sees access attempts for their business in the agent trace
        wf = wfs.start_workflow(db, org.id, WorkflowType.INBOUND, goal="Customer portal sign-in request",
                                customer_id=customer.id if customer else None)
        wfs.record(db, wf, "access", "Verify portal sign-in request",
                   TraceStatus.COMPLETED if not failed else TraceStatus.BLOCKED,
                   ("Verified registered customer — sign-in code sent" if not failed
                    else f"Access denied ({'; '.join(failed)})"),
                   detail={"checks": [{"check": n, "passed": ok} for n, ok in checks]},
                   state=WorkflowState.COMPLETED if not failed else WorkflowState.BLOCKED)

    message = GENERIC_MESSAGE.format(ttl=settings.portal_code_ttl_minutes)
    if failed:
        db.commit()
        return AccessRequestResult(req.id, message, verified=False)

    code = f"{secrets.randbelow(1_000_000):06d}"
    req.status = "VERIFIED"
    req.customer_id = customer.id
    req.code_hash = _hash_code(req.id, code)
    req.expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.portal_code_ttl_minutes)
    db.commit()
    try:
        container.email_provider.send(OutgoingEmail(
            to=customer.email, subject=f"Your {org.name} portal sign-in code: {code}",
            body=f"Hi {customer.name},\n\nYour sign-in code for the {org.name} customer portal is {code}. "
                 f"It expires in {settings.portal_code_ttl_minutes} minutes.\n\nIf you didn't request it, ignore this email.",
            from_address=settings.email_from_address or f"{org.name} <no-reply@example.com>",
            idempotency_key=f"portal-code-{req.id}"))
    except EmailSendError as exc:
        logger.warning("Could not send portal code: %s", exc)
        raise GrowthOSError("We couldn't send the sign-in email right now. Please try again shortly.") from exc
    dev_code = code if settings.email_provider in ("mock", "") else None
    return AccessRequestResult(req.id, message, verified=True, dev_code=dev_code)


def verify_code(db: Session, request_id: uuid.UUID, code: str) -> tuple[str, Customer]:
    req = db.scalar(select(PortalAccessRequest).where(PortalAccessRequest.id == request_id).with_for_update())
    invalid = PortalAuthError("Invalid or expired code. Request a new one.")
    if req is None or req.status != "VERIFIED" or req.code_hash is None:
        raise invalid
    if req.expires_at is None or req.expires_at < datetime.now(timezone.utc):
        raise invalid
    req.attempts += 1
    if req.attempts > MAX_CODE_ATTEMPTS:
        req.status = "LOCKED"
        db.commit()
        raise invalid
    if not hmac.compare_digest(req.code_hash, _hash_code(req.id, code.strip())):
        db.commit()
        raise invalid
    customer = db.get(Customer, req.customer_id)
    if customer is None or is_suppressed(db, customer.organization_id, customer.email_hash):
        raise invalid
    req.status = "USED"
    user = db.scalar(select(User).where(User.customer_id == customer.id))
    if user is None:
        # Portal users have no password: sign-in is always Business ID + emailed code.
        user = User(organization_id=customer.organization_id, email=customer.email, name=customer.name,
                    role=UserRole.CUSTOMER.value, customer_id=customer.id,
                    password_hash=hash_password(secrets.token_urlsafe(32)))
        db.add(user)
    db.commit()
    return create_access_token(user.id, user.organization_id), customer
