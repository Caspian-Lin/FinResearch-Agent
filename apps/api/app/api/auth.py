"""Auth router: register, login, and the protected /me endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, Token, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    """Create a new user. Passwords are bcrypt-hashed before storage.

    Returns 409 if the email is already registered.
    """
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/login",
    response_model=Token,
    summary="Log in and receive a JWT access token",
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> Token:
    """Verify credentials and issue a JWT. Returns 401 on bad credentials."""
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive account",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(subject=str(user.id))
    return Token(access_token=token.token, expires_in=token.expires_in)


@router.get(
    "/me",
    response_model=UserRead,
    summary="Return the currently authenticated user",
)
def me(current_user: User = Depends(get_current_user)) -> User:
    """Protected route — requires a valid bearer token."""
    return current_user
