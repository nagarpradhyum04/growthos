import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, current_user
from app.db import get_db
from app.errors import InvalidStateError
from app.models import Campaign, Email, EmailReply, Lead
from app.models.enums import SENT_LIKE_STATUSES, CampaignStatus, LeadStatus
from app.schemas import CampaignIn, CampaignOut, CampaignSummary
from app.services.common import get_owned
from app.services.safety import max_followups_for

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

# Prospects the Find-customers workflow would still work on (same rule as Orchestrator.run_goal).
WAITING_FILTER = (Lead.disabled.is_(False), Lead.status.in_([LeadStatus.NEW, LeadStatus.RESEARCHED, LeadStatus.QUALIFIED]))


def best_campaign_id(db: Session, organization_id):
    """Default campaign for Find customers: the active one with the most prospects waiting, else the newest active."""
    waiting = func.count(Lead.id)
    row = db.execute(select(Campaign.id, waiting).outerjoin(Lead, (Lead.campaign_id == Campaign.id) & WAITING_FILTER[0]
                                                         & WAITING_FILTER[1])
                     .where(Campaign.organization_id == organization_id, Campaign.status == CampaignStatus.ACTIVE)
                     .group_by(Campaign.id, Campaign.created_at)
                     .order_by(waiting.desc(), Campaign.created_at.desc())).first()
    return row[0] if row else None


def _summary(db: Session, c: Campaign) -> CampaignSummary:
    def count(stmt) -> int:
        return db.scalar(stmt) or 0

    return CampaignSummary(
        **CampaignOut.model_validate(c).model_dump(),
        leads=count(select(func.count(Lead.id)).where(Lead.campaign_id == c.id)),
        prospects_waiting=count(select(func.count(Lead.id)).where(Lead.campaign_id == c.id, *WAITING_FILTER)),
        qualified_leads=count(select(func.count(Lead.id)).where(Lead.campaign_id == c.id, Lead.qualified.is_(True))),
        emails_sent=count(select(func.count(Email.id)).where(Email.campaign_id == c.id,
                                                             Email.status.in_(SENT_LIKE_STATUSES))),
        replies=count(select(func.count(EmailReply.id)).where(EmailReply.campaign_id == c.id)),
        effective_max_followups=max_followups_for(c),
    )


@router.get("", response_model=list[CampaignSummary])
def list_campaigns(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    campaigns = db.scalars(
        select(Campaign).where(Campaign.organization_id == cu.org_id).order_by(Campaign.created_at.desc())
    ).all()
    return [_summary(db, c) for c in campaigns]


@router.post("", response_model=CampaignSummary, status_code=201)
def create_campaign(body: CampaignIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    campaign = Campaign(organization_id=cu.org_id, **body.model_dump())
    db.add(campaign)
    db.commit()
    return _summary(db, campaign)


@router.get("/{campaign_id}", response_model=CampaignSummary)
def get_campaign(campaign_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return _summary(db, get_owned(db, Campaign, campaign_id, cu.org_id))


@router.put("/{campaign_id}", response_model=CampaignSummary)
def update_campaign(campaign_id: uuid.UUID, body: CampaignIn, cu: CurrentUser = Depends(current_user),
                    db: Session = Depends(get_db)):
    campaign = get_owned(db, Campaign, campaign_id, cu.org_id)
    for key, value in body.model_dump().items():
        setattr(campaign, key, value)
    db.commit()
    return _summary(db, campaign)


def _set_status(db: Session, cu: CurrentUser, campaign_id: uuid.UUID, target: CampaignStatus,
                allowed_from: set[CampaignStatus]) -> CampaignSummary:
    campaign = get_owned(db, Campaign, campaign_id, cu.org_id, for_update=True)
    if campaign.status not in allowed_from:
        raise InvalidStateError(f"Cannot change a {campaign.status.value} campaign to {target.value}")
    campaign.status = target
    db.commit()
    return _summary(db, campaign)


@router.post("/{campaign_id}/pause", response_model=CampaignSummary)
def pause_campaign(campaign_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return _set_status(db, cu, campaign_id, CampaignStatus.PAUSED, {CampaignStatus.ACTIVE, CampaignStatus.PAUSED})


@router.post("/{campaign_id}/resume", response_model=CampaignSummary)
def resume_campaign(campaign_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return _set_status(db, cu, campaign_id, CampaignStatus.ACTIVE, {CampaignStatus.PAUSED, CampaignStatus.ACTIVE})


@router.post("/{campaign_id}/complete", response_model=CampaignSummary)
def complete_campaign(campaign_id: uuid.UUID, cu: CurrentUser = Depends(current_user),
                      db: Session = Depends(get_db)):
    return _set_status(db, cu, campaign_id, CampaignStatus.COMPLETED,
                       {CampaignStatus.ACTIVE, CampaignStatus.PAUSED})
