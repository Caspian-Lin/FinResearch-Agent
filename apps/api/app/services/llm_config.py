"""LLM config resolver — merges per-user settings with global defaults (FRA-93).

When a user has configured their own LLM settings (via ``PUT /settings/llm``),
those values take priority. Missing fields fall back to the global ``.env``
defaults. This is the single entry point for all LLM-touching components
(Planner, Sentiment classifier) to obtain resolved credentials.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt_api_key
from app.models.user_llm_config import UserLLMConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedLLMConfig:
    """Fully resolved LLM configuration ready for adapter construction."""

    provider: str
    api_key: str
    base_url: str
    model: str
    temperature: float
    timeout: float


def resolve_llm_config(user_id: uuid.UUID, db: Session) -> ResolvedLLMConfig:
    """Resolve LLM config for *user_id*: user config overrides global defaults.

    Returns a :class:`ResolvedLLMConfig` with all fields populated. If the user
    has no row in ``user_llm_configs``, or individual fields are null, the
    corresponding global default from ``settings`` is used.
    """
    row = db.scalar(select(UserLLMConfig).where(UserLLMConfig.user_id == user_id))

    if row is None:
        return _global_defaults()

    api_key = settings.openai_api_key
    if row.encrypted_api_key:
        try:
            api_key = decrypt_api_key(row.encrypted_api_key)
        except Exception:
            logger.warning("failed to decrypt API key for user %s; using global default", user_id)

    return ResolvedLLMConfig(
        provider=row.provider or settings.planner_provider,
        api_key=api_key,
        base_url=row.base_url or settings.openai_base_url,
        model=row.model or settings.openai_model,
        temperature=row.temperature
        if row.temperature is not None
        else settings.planner_temperature,
        timeout=float(settings.llm_request_timeout_seconds),
    )


def _global_defaults() -> ResolvedLLMConfig:
    """Return global defaults from ``settings`` (no user override)."""
    return ResolvedLLMConfig(
        provider=settings.planner_provider,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        temperature=settings.planner_temperature,
        timeout=float(settings.llm_request_timeout_seconds),
    )


__all__ = ["ResolvedLLMConfig", "resolve_llm_config"]
