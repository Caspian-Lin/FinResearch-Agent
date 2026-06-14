"""Pydantic v2 schemas for authentication requests and responses."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _normalize_email(v: str) -> str:
    """Trim surrounding whitespace and lowercase the address.

    Pydantic's ``EmailStr`` already validates and lower-cases the domain via
    ``email_validator``, but we apply an explicit ``strip().lower()`` here so
    that ``"Foo@Bar.com "`` and ``"foo@bar.com"`` collapse to the same key —
    preventing duplicate-account and lookup mismatches.
    """
    if not isinstance(v, str):
        return v
    return v.strip().lower()


class UserCreate(BaseModel):
    """Payload for POST /auth/register."""

    model_config = ConfigDict(populate_by_name=True)

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return _normalize_email(v)


class UserRead(BaseModel):
    """Public representation of a User, returned by /auth/register and /me."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    """JWT bearer token response for POST /auth/login.

    ``expires_in`` is the token lifetime in seconds (RFC 6749 convention),
    derived from ``settings.jwt_expire_minutes``.
    """

    access_token: str
    token_type: str = Field(default="bearer")
    expires_in: int = Field(description="Access token lifetime in seconds.")


class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""

    model_config = ConfigDict(populate_by_name=True)

    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return _normalize_email(v)
