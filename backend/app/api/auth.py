from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, current_user
from app.db import get_db
from app.models import BusinessProfile, Organization, User
from app.schemas import LoginRequest, MeResponse, OrganizationOut, RegisterRequest, TokenResponse, UserOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    org = Organization(name=body.organization_name.strip())
    db.add(org)
    db.flush()
    user = User(organization_id=org.id, email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.add(BusinessProfile(organization_id=org.id, company_name=org.name))
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id, org.id))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return TokenResponse(access_token=create_access_token(user.id, user.organization_id), role=user.role)


@router.get("/me", response_model=MeResponse)
def me(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    org = db.get(Organization, cu.org_id)
    return MeResponse(user=UserOut.model_validate(cu.user), organization=OrganizationOut.model_validate(org))
