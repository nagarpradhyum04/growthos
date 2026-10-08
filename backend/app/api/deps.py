"""Shared API dependencies: DB session, current user/organization, service container."""
import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import decode_token
from app.services.container import Container, get_container

bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    user: User

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def org_id(self) -> uuid.UUID:
        return self.user.organization_id


def _authenticated(credentials: HTTPAuthorizationCredentials | None, db: Session) -> User:
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated",
                                 headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    try:
        payload = decode_token(credentials.credentials, "access")
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized from None
    # The org in the token must still match the user's org.
    if user is None or str(user.organization_id) != payload.get("org"):
        raise unauthorized
    return user


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> CurrentUser:
    """Business-owner endpoints. Customer (portal) accounts are rejected server-side, not just hidden in the UI."""
    user = _authenticated(credentials, db)
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Business owner access required")
    return CurrentUser(user=user)


@dataclass
class CurrentCustomer:
    user: User
    customer: "Customer"

    @property
    def org_id(self) -> uuid.UUID:
        return self.user.organization_id


def current_customer(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> CurrentCustomer:
    """Customer portal endpoints: the customer is taken from the token, never from the request."""
    from app.models import Customer

    user = _authenticated(credentials, db)
    if user.role != "customer" or user.customer_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer portal access only")
    customer = db.get(Customer, user.customer_id)
    if customer is None or customer.organization_id != user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer portal access only")
    return CurrentCustomer(user=user, customer=customer)


def container() -> Container:
    return get_container()
