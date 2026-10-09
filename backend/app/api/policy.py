from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, current_user
from app.db import get_db
from app.errors import InvalidStateError
from app.services.escalation import RED
from app.services.social_service import PLATFORM_CAPTION_LIMITS
from app.services.policy import get_or_create_policy, get_policy

router = APIRouter(prefix="/policy", tags=["policy"])


class PolicyIn(BaseModel):
    max_messages_per_contact_30d: int = Field(ge=1, le=30)
    min_hours_between_messages: int = Field(ge=0, le=24 * 30)
    blocked_domains: list[str] = Field(default_factory=list, max_length=200)
    banned_phrases: list[str] = Field(default_factory=list, max_length=200)
    escalation_rules: dict[str, str]
    large_order_threshold: float = Field(ge=0)
    auto_handle_routine: bool
    warranty_auto_approve: bool
    lifecycle_enabled: bool
    lifecycle_rules: dict[str, int]
    lifecycle_max_per_7d: int = Field(ge=0, le=20)
    social_weekly_enabled: bool = True
    social_platforms: list[str] = Field(default_factory=lambda: ["instagram", "linkedin", "facebook"], max_length=5)


def policy_dict(p) -> dict:
    return {k: getattr(p, k) for k in PolicyIn.model_fields} | {
        "large_order_threshold": float(p.large_order_threshold), "locked_categories": sorted(RED)}


@router.get("")
def read_policy(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return policy_dict(get_policy(db, cu.org_id))


@router.put("")
def update_policy(body: PolicyIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    for category, mode in body.escalation_rules.items():
        if mode not in ("escalate", "automate"):
            raise InvalidStateError(f"Rule for {category} must be 'escalate' or 'automate'.")
        if category in RED and mode != "escalate":
            raise InvalidStateError(f"{category} must always be escalated to a human.")
    unknown = [x for x in body.social_platforms if x not in PLATFORM_CAPTION_LIMITS]
    if unknown:
        raise InvalidStateError(f"Unsupported social platform(s): {', '.join(unknown)}")
    p = get_or_create_policy(db, cu.org_id)
    for key, value in body.model_dump().items():
        setattr(p, key, [v.strip() for v in value if v.strip()] if isinstance(value, list) else value)
    db.commit()
    return policy_dict(p)
