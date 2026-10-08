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


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> CurrentUser:
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
    return CurrentUser(user=user)


def container() -> Container:
    return get_container()
