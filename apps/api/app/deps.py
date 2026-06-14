"""Shared FastAPI dependencies.

``get_current_user`` parses an ``Authorization: Bearer <token>`` header,
verifies the JWT against ``settings.jwt_secret`` (HS256), and resolves the
``sub`` claim to a ``User`` row. Any failure yields HTTP 401.
"""

from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User

# scheme auto-reads "Authorization: Bearer <token>"; no auto-error so we can
# return a uniform 401 on missing/invalid tokens.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the bearer token to the active User, or raise 401."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise credentials_exc

    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise credentials_exc from None

    sub = payload.get("sub")
    if not sub:
        raise credentials_exc

    try:
        user_id = uuid.UUID(str(sub))
    except (ValueError, TypeError):
        raise credentials_exc from None

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        raise credentials_exc
    return user
