"""Password hashing and JWT helpers."""
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: uuid.UUID, organization_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "org": str(organization_id),
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict:
    """Raises jwt.PyJWTError on any problem."""
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    if payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def create_unsubscribe_token(contact_id: uuid.UUID, organization_id: uuid.UUID) -> str:
    """Long-lived signed token embedded in every outgoing email's unsubscribe link."""
    payload = {"sub": str(contact_id), "org": str(organization_id), "typ": "unsubscribe"}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=ALGORITHM)
