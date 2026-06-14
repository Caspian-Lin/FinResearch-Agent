"""Password hashing and JWT helpers.

Uses passlib's bcrypt CryptContext for password hashing and PyJWT for
encoding/decoding HS256 access tokens. Plaintext passwords never leave the
request boundary — only the bcrypt hash is persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass(frozen=True, slots=True)
class AccessToken:
    """An issued access token plus its lifetime in seconds."""

    token: str
    expires_in: int


def hash_password(plain: str) -> str:
    """Return a bcrypt hash for the given plaintext password."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if ``plain`` matches the stored ``hashed`` password."""
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str, expires_minutes: int | None = None) -> AccessToken:
    """Encode a JWT access token for ``subject`` (the user id, as a string).

    The expiry is taken from ``settings.jwt_expire_minutes`` unless an
    explicit override is supplied. Returns the encoded token together with
    its lifetime in seconds so callers can populate ``expires_in`` in the
    response without re-deriving it.
    """
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    expires_in = minutes * 60
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return AccessToken(token=token, expires_in=expires_in)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT.

    Raises ``jwt.PyJWTError`` subclasses (``ExpiredSignatureError``,
    ``InvalidTokenError``) on any validation failure — callers should
    translate those into a 401 response.
    """
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
