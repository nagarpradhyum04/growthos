"""Shared memory: lets agents build on each other's work instead of acting as isolated bots.

Structured data stays in its relational tables (emails, replies, purchases...). Memory entries hold the
distilled facts/insights agents pass between each other. Plain SQL; no vector store needed.
"""
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Customer,
    Email,
    EmailReply,
    MemoryEntry,
    Message,
    Purchase,
    Product,
)
from app.models.enums import SENT_LIKE_STATUSES


def remember(db: Session, organization_id: uuid.UUID, *, scope: str, subject_id, category: str, key: str,
             content: str, source: str, data: dict | None = None, importance: int = 1,
             workflow_id=None, replace: bool = True) -> MemoryEntry:
    """Write a memory entry. With replace=True an entry with the same (scope, subject, category, key) is updated."""
    entry = None
    if replace:
        entry = db.scalar(select(MemoryEntry).where(
            MemoryEntry.organization_id == organization_id, MemoryEntry.scope == scope,
            MemoryEntry.subject_id == subject_id, MemoryEntry.category == category, MemoryEntry.key == key))
    if entry is None:
        entry = MemoryEntry(organization_id=organization_id, scope=scope, subject_id=subject_id,
                            category=category, key=key, content=content, source=source)
        db.add(entry)
    entry.content = content[:4000]
    entry.data = data or {}
    entry.source = source
    entry.importance = importance
    entry.workflow_id = workflow_id
    db.flush()
    return entry


def recall(db: Session, organization_id: uuid.UUID, *, scope: str | None = None, subject_id=None,
           categories: list[str] | None = None, limit: int = 20) -> list[MemoryEntry]:
    stmt = select(MemoryEntry).where(MemoryEntry.organization_id == organization_id)
    if scope:
        stmt = stmt.where(MemoryEntry.scope == scope)
    if subject_id is not None:
        stmt = stmt.where(MemoryEntry.subject_id == subject_id)
    if categories:
        stmt = stmt.where(MemoryEntry.category.in_(categories))
    return list(db.scalars(stmt.order_by(MemoryEntry.importance.desc(), MemoryEntry.updated_at.desc()).limit(limit)))


def forget_subject(db: Session, organization_id: uuid.UUID, subject_id) -> None:
    """Forget Me: memory about a person/lead is deleted with the rest of their data."""
    db.execute(delete(MemoryEntry).where(MemoryEntry.organization_id == organization_id,
                                         MemoryEntry.subject_id == subject_id))


def as_context(entries: list[MemoryEntry]) -> list[dict]:
    return [{"category": e.category, "key": e.key, "content": e.content, "source": e.source} for e in entries]


def learned_insights(db: Session, organization_id: uuid.UUID, limit: int = 5) -> list[MemoryEntry]:
    return recall(db, organization_id, scope="business", categories=["insight"], limit=limit)


def lead_context(db: Session, lead) -> dict:
    """What outreach/follow-up/reply agents see from memory for a lead."""
    return {
        "lead_facts": as_context(recall(db, lead.organization_id, scope="lead", subject_id=lead.id, limit=15)),
        "learned_insights": as_context(learned_insights(db, lead.organization_id)),
    }


def conversation_history(db: Session, contact_id) -> list[dict]:
    emails = db.scalars(select(Email).where(Email.contact_id == contact_id, Email.status.in_(SENT_LIKE_STATUSES))
                        .order_by(Email.sent_at)).all()
    replies = db.scalars(select(EmailReply).where(EmailReply.contact_id == contact_id)
                         .order_by(EmailReply.received_at)).all()
    items = [{"direction": "outbound", "at": e.sent_at.isoformat() if e.sent_at else None, "subject": e.subject,
              "body": e.body} for e in emails]
    items += [{"direction": "inbound", "at": r.received_at.isoformat(), "subject": r.subject, "body": r.body,
               "classification": r.classification.value if r.classification else None} for r in replies]
    return sorted(items, key=lambda i: i["at"] or "")


def customer_context(db: Session, customer: Customer, limit_messages: int = 10) -> dict:
    """Shared context for agents acting on a customer (support, email intelligence, lifecycle)."""
    purchases = db.execute(
        select(Purchase, Product).join(Product, Product.id == Purchase.product_id)
        .where(Purchase.customer_id == customer.id)).all()
    messages = db.scalars(select(Message).where(Message.customer_id == customer.id)
                          .order_by(Message.created_at.desc()).limit(limit_messages)).all()
    return {
        "customer": {"name": customer.name, "company": customer.company, "status": customer.status.value},
        "products": [{"product": p.name, "purchased_at": pu.purchased_at.isoformat(),
                      "warranty_expires_at": pu.warranty_expires_at.isoformat() if pu.warranty_expires_at else None,
                      "status": pu.status.value} for pu, p in purchases],
        "recent_messages": [{"from": m.sender.value, "body": m.body[:500]} for m in reversed(messages)],
        "memory": as_context(recall(db, customer.organization_id, scope="customer", subject_id=customer.id, limit=10)),
    }
