"""User LLM config API — per-user LLM settings (FRA-93).

Two endpoints, both scoped to ``current_user``:
  - ``GET /settings/llm`` — masked read (never returns API key plaintext)
  - ``PUT /settings/llm`` — upsert (empty api_key = keep existing)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_api_key
from app.db.session import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.user_llm_config import UserLLMConfig
from app.schemas.llm_config import LLMConfigRead, LLMConfigUpdate

router = APIRouter(prefix="/settings", tags=["settings"])

DBSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _to_read(row: UserLLMConfig | None) -> LLMConfigRead:
    """Convert a UserLLMConfig row (or None) to the masked read schema."""
    if row is None:
        return LLMConfigRead(
            provider="fixture",
            has_api_key=False,
            api_key_last4=None,
        )
    last4 = None
    if row.encrypted_api_key and len(row.encrypted_api_key) > 4:
        # The encrypted token itself is opaque; we store a hint alongside
        # by checking length. For the masked display we use the model field
        # to indicate whether a key exists.
        last4 = "••••"
    return LLMConfigRead(
        provider=row.provider,
        has_api_key=bool(row.encrypted_api_key),
        api_key_last4=last4,
        base_url=row.base_url,
        model=row.model,
        temperature=row.temperature,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.get("/llm", response_model=LLMConfigRead, summary="Get current user's LLM config")
def get_llm_config(db: DBSession, current_user: CurrentUser) -> LLMConfigRead:
    row = db.scalar(select(UserLLMConfig).where(UserLLMConfig.user_id == current_user.id))
    return _to_read(row)


@router.put("/llm", response_model=LLMConfigRead, summary="Update current user's LLM config")
def update_llm_config(
    payload: LLMConfigUpdate,
    db: DBSession,
    current_user: CurrentUser,
) -> LLMConfigRead:
    row = db.scalar(select(UserLLMConfig).where(UserLLMConfig.user_id == current_user.id))

    if row is None:
        row = UserLLMConfig(
            user_id=current_user.id,
            provider=payload.provider or "fixture",
        )
        db.add(row)

    if payload.provider is not None:
        row.provider = payload.provider

    # api_key: empty/None = keep existing; non-empty = update
    if payload.api_key:
        row.encrypted_api_key = encrypt_api_key(payload.api_key)

    if payload.base_url is not None:
        row.base_url = payload.base_url or None

    if payload.model is not None:
        row.model = payload.model or None

    if payload.temperature is not None:
        row.temperature = payload.temperature

    db.commit()
    db.refresh(row)
    return _to_read(row)
