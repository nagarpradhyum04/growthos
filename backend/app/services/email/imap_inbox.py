"""Reads prospect replies from your mailbox over IMAP (IMAP_HOST set) so they reach GrowthOS automatically.

- Messages are read with BODY.PEEK, so nothing is marked as read in your mailbox.
- Only replies to emails GrowthOS sent are imported: matched by In-Reply-To/References (our Message-ID carries
  the email id), otherwise by the sender being a contact we emailed. Everything else in the inbox is ignored.
- Each message is imported once (deduplicated by its Message-ID).
"""
import email
import imaplib
import logging
import re
import uuid
from datetime import date, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import NotFoundError
from app.models import Contact, Email, EmailReply
from app.models.enums import SENT_LIKE_STATUSES
from app.services import jobs, reply_service
from app.services.suppression import hash_email

logger = logging.getLogger(__name__)
_OUR_ID = re.compile(r"growthos\.([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I)
_QUOTE_START = re.compile(r"^(On .+wrote:|-{2,}\s*Original Message\s*-{2,}|From: .+|Sent from my )", re.I)


def _header(msg, name: str) -> str:
    raw = msg.get(name, "")
    try:
        return str(make_header(decode_header(raw)))
    except Exception:  # noqa: BLE001
        return raw


def new_text(body: str) -> str:
    """Only what the person wrote: drop quoted history and signatures that mail clients append."""
    lines = []
    for line in body.splitlines():
        if _QUOTE_START.match(line.strip()):
            break
        if line.lstrip().startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _plain_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                return re.sub(r"<[^>]+>", " ", html)
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


def match_email(db: Session, refs: str, from_address: str) -> Email | None:
    """Which email we sent is this a reply to?"""
    for m in _OUR_ID.finditer(refs or ""):
        found = db.get(Email, uuid.UUID(m.group(1)))
        if found is not None:
            return found
    if not from_address:
        return None
    return db.scalar(select(Email).join(Contact, Contact.id == Email.contact_id)
                     .where(Contact.email_hash == hash_email(from_address), Email.status.in_(SENT_LIKE_STATUSES))
                     .order_by(Email.sent_at.desc()))


def import_message(db: Session, raw: bytes) -> str:
    """Import one raw RFC822 message. Returns 'recorded' | 'duplicate' | 'ignored'."""
    msg = email.message_from_bytes(raw)
    message_id = (msg.get("Message-ID") or "").strip() or None
    if message_id and db.scalar(select(EmailReply.id).where(EmailReply.external_id == message_id)):
        return "duplicate"
    from_address = parseaddr(msg.get("From", ""))[1].lower()
    refs = f"{msg.get('In-Reply-To', '')} {msg.get('References', '')}"
    sent = match_email(db, refs, from_address)
    if sent is None:
        return "ignored"
    try:
        reply, created = reply_service.record_reply(
            db, sent.organization_id, subject=_header(msg, "Subject"), body=new_text(_plain_body(msg)) or "(empty reply)",
            email_id=sent.id, from_address=from_address, external_id=message_id)
    except NotFoundError:
        db.rollback()
        return "ignored"
    db.commit()
    if created and reply.analyzed_at is None:
        jobs.enqueue(db, "analyze_reply", {"reply_id": str(reply.id), "lead_id": str(reply.lead_id),
                                           "contact_id": str(reply.contact_id)},
                     organization_id=reply.organization_id, dedupe_key=f"analyze_reply:{reply.id}")
        db.commit()
    return "recorded" if created else "duplicate"


def poll_inbox(db: Session, settings: Settings, days: int = 7, limit: int = 200) -> dict:
    """Check the mailbox once. Errors are returned (and logged), never raised, so the worker keeps running."""
    user = settings.imap_username or settings.smtp_username
    password = settings.imap_password or settings.smtp_password
    out = {"recorded": 0, "duplicate": 0, "ignored": 0}
    try:
        box = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
        box.login(user, password)
        box.select(settings.imap_folder, readonly=True)
        since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
        _, data = box.search(None, f'(SINCE "{since}")')
        ids = (data[0].split() if data and data[0] else [])[-limit:]
        for num in ids:
            _, parts = box.fetch(num, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if raw:
                out[import_message(db, raw)] += 1
        box.logout()
    except imaplib.IMAP4.error as exc:
        out["error"] = f"IMAP login/read failed: {exc}"
    except OSError as exc:
        out["error"] = f"Cannot reach {settings.imap_host}:{settings.imap_port}: {type(exc).__name__}"
    if out.get("error"):
        logger.warning("Inbox poll: %s", out["error"])
    return out
