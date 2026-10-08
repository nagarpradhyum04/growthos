from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, current_user
from app.db import get_db
from app.models import BusinessProfile, Organization
from app.schemas import BusinessProfileIn, BusinessProfileOut, OrganizationOut, OrganizationSettingsUpdate

router = APIRouter(tags=["organization"])


def _profile(db: Session, cu: CurrentUser) -> BusinessProfile:
    profile = db.scalar(select(BusinessProfile).where(BusinessProfile.organization_id == cu.org_id))
    if profile is None:
        profile = BusinessProfile(organization_id=cu.org_id)
        db.add(profile)
        db.flush()
    return profile


@router.get("/business-profile", response_model=BusinessProfileOut)
def get_business_profile(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    profile = _profile(db, cu)
    db.commit()
    return profile


@router.put("/business-profile", response_model=BusinessProfileOut)
def update_business_profile(body: BusinessProfileIn, cu: CurrentUser = Depends(current_user),
                            db: Session = Depends(get_db)):
    profile = _profile(db, cu)
    for key, value in body.model_dump().items():
        if isinstance(value, list):
            value = [v.strip() for v in value if v.strip()]
        setattr(profile, key, value)
    db.commit()
    return profile


@router.patch("/organization/settings", response_model=OrganizationOut)
def update_settings(body: OrganizationSettingsUpdate, cu: CurrentUser = Depends(current_user),
                    db: Session = Depends(get_db)):
    org = db.get(Organization, cu.org_id)
    org.automated_sending_enabled = body.automated_sending_enabled
    db.commit()
    return org
