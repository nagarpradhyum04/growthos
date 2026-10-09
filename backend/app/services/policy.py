"""Safety Agent / policy layer: deterministic, owner-configurable rules. No LLM involved.

- Hard rules (BLOCK) are enforced inside can_send(), so no send path can skip them.
- Soft rules (ESCALATE) force a human decision even when automation is enabled.
"""
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BusinessPolicy, BusinessProfile, Contact, Email
from app.models.policy import DEFAULT_BANNED_PHRASES, DEFAULT_ESCALATION_RULES, DEFAULT_LIFECYCLE_RULES
from app.models.enums import SENT_LIKE_STATUSES


def default_policy(organization_id: uuid.UUID) -> BusinessPolicy:
    return BusinessPolicy(
        organization_id=organization_id, max_messages_per_contact_30d=4, min_hours_between_messages=0,
        blocked_domains=[], banned_phrases=list(DEFAULT_BANNED_PHRASES),
        escalation_rules=dict(DEFAULT_ESCALATION_RULES), large_order_threshold=10000, auto_handle_routine=True,
        warranty_auto_approve=False, lifecycle_enabled=True, lifecycle_rules=dict(DEFAULT_LIFECYCLE_RULES),
        lifecycle_max_per_7d=1, social_weekly_enabled=True, social_platforms=["instagram", "linkedin", "facebook"],
    )


def get_policy(db: Session, organization_id: uuid.UUID) -> BusinessPolicy:
    """Read-only: the saved policy, or an unsaved object holding the defaults.
    (Never inserts — reads happen inside send transactions and must not take extra locks.)"""
    policy = db.scalar(select(BusinessPolicy).where(BusinessPolicy.organization_id == organization_id))
    return policy if policy is not None else default_policy(organization_id)


def get_or_create_policy(db: Session, organization_id: uuid.UUID) -> BusinessPolicy:
    policy = db.scalar(select(BusinessPolicy).where(BusinessPolicy.organization_id == organization_id))
    if policy is None:
        policy = default_policy(organization_id)
        db.add(policy)
        db.flush()
    return policy


@dataclass
class PolicyFinding:
    code: str
    label: str
    detail: str
    severity: str  # "block" | "escalate"


def _recent_sends(db: Session, email: Email, contact: Contact, since: datetime) -> list[datetime]:
    rows = db.scalars(
        select(Email.sent_at)
        .join(Contact, Contact.id == Email.contact_id)
        .where(Email.organization_id == email.organization_id, Contact.email_hash == contact.email_hash,
               Email.status.in_(SENT_LIKE_STATUSES), Email.sent_at.is_not(None), Email.sent_at >= since,
               Email.id != email.id)
        .order_by(Email.sent_at.desc())
    ).all()
    return list(rows)


def hard_findings(db: Session, email: Email, contact: Contact) -> list[PolicyFinding]:
    """Rules that BLOCK a send. Called from can_send()."""
    policy = get_policy(db, email.organization_id)
    now = datetime.now(timezone.utc)
    findings: list[PolicyFinding] = []

    recent = _recent_sends(db, email, contact, now - timedelta(days=30))
    if len(recent) >= policy.max_messages_per_contact_30d:
        last = recent[0]
        days = (now - last).days
        findings.append(PolicyFinding(
            "frequency_limit_reached", "Campaign frequency limit respected",
            f"Contacted {len(recent)} time(s) in the last 30 days (last {days} day(s) ago); "
            f"limit is {policy.max_messages_per_contact_30d} messages / 30 days", "block"))
    if policy.min_hours_between_messages and recent:
        gap_h = (now - recent[0]).total_seconds() / 3600
        if gap_h < policy.min_hours_between_messages:
            findings.append(PolicyFinding(
                "too_soon_since_last_message", "Minimum gap between messages respected",
                f"Last message {gap_h:.0f}h ago; policy requires {policy.min_hours_between_messages}h", "block"))

    domain = (contact.email or "").rsplit("@", 1)[-1].lower() if contact.email else ""
    blocked = {d.lower().lstrip("@") for d in policy.blocked_domains}
    if domain and domain in blocked:
        findings.append(PolicyFinding("blocked_domain", "Recipient matches targeting rules",
                                      f"Domain {domain} is excluded by your targeting rules", "block"))

    text = f"{email.subject}\n{email.body}".lower()
    hits = [p for p in policy.banned_phrases if p and p.lower() in text]
    if hits:
        findings.append(PolicyFinding("banned_phrase", "No banned phrases",
                                      f"Contains banned phrase(s): {', '.join(hits)}", "block"))
    if not email.subject.strip() or len(email.body.strip()) < 20:
        findings.append(PolicyFinding("missing_content", "Subject and body present",
                                      "Subject or body is missing", "block"))
    return findings


_CLAIM_PATTERNS = [
    (re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%"), "a percentage claim"),
    (re.compile(r"\bguarantee[sd]?\b", re.I), "a guarantee"),
    (re.compile(r"\b(#1|number one|best in (the )?(industry|market)|industry[- ]leading)\b", re.I), "a superlative claim"),
    (re.compile(r"\b(\d+x|\d+ times) (faster|more|better)\b", re.I), "a performance multiple"),
]
_SENSITIVE_OUTBOUND = re.compile(r"\b(discount|refund|free of charge|contract|legal|lawsuit|price match)\b", re.I)


def soft_findings(db: Session, email: Email) -> list[PolicyFinding]:
    """Rules that require a human (ESCALATE): unsupported claims, sensitive commercial terms."""
    profile = db.scalar(select(BusinessProfile).where(BusinessProfile.organization_id == email.organization_id))
    known = " ".join([profile.value_proposition, profile.key_differentiators, profile.products_services,
                      profile.company_description]).lower() if profile else ""
    findings: list[PolicyFinding] = []
    for pattern, label in _CLAIM_PATTERNS:
        for match in pattern.finditer(email.body):
            if match.group(0).lower() not in known:
                findings.append(PolicyFinding(
                    "unsupported_claim", "No unsupported claims",
                    f"Contains {label} (“{match.group(0)}”) not found in your business profile", "escalate"))
                break
    sensitive = _SENSITIVE_OUTBOUND.search(email.body)
    if sensitive:
        findings.append(PolicyFinding("sensitive_terms", "No sensitive commercial terms",
                                      f"Mentions “{sensitive.group(0)}” — commercial terms need a human", "escalate"))
    return findings


@dataclass
class PolicyDecision:
    outcome: str  # ALLOW | BLOCK | ESCALATE
    reasons: list[str] = field(default_factory=list)
    findings: list[PolicyFinding] = field(default_factory=list)

    def explain(self) -> str:
        if self.outcome == "ALLOW":
            return "All safety and policy rules passed"
        return "; ".join(f.detail for f in self.findings) or ", ".join(r.replace("_", " ") for r in self.reasons)

    def to_dict(self) -> dict:
        return {"outcome": self.outcome, "reasons": self.reasons, "explanation": self.explain(),
                "findings": [f.__dict__ for f in self.findings]}


def evaluate_outbound(db: Session, email: Email, *, ignore_approval: bool = True) -> PolicyDecision:
    """Full Safety Agent verdict for an outbound email.

    ignore_approval=True evaluates the email as if a human had approved it — used before review to tell
    the owner whether it *could* be sent. The real send still calls can_send() without exceptions.
    """
    from app.services.safety import can_send

    decision = can_send(db, email)
    blocking = [r for r in decision.reasons if not (ignore_approval and r == "not_approved")]
    findings = [f for f in decision.findings if f.code in blocking]
    if blocking:
        return PolicyDecision("BLOCK", blocking, findings)
    soft = soft_findings(db, email)
    if soft:
        return PolicyDecision("ESCALATE", [f.code for f in soft], soft)
    return PolicyDecision("ALLOW")


def count_sent_last_30d(db: Session, organization_id: uuid.UUID) -> int:
    return db.scalar(select(func.count(Email.id)).where(
        Email.organization_id == organization_id, Email.sent_at >= datetime.now(timezone.utc) - timedelta(days=30))) or 0
