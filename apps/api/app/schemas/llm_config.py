"""Pydantic schemas for user LLM config API (FRA-93).

The read schema **never** includes the API key plaintext — only ``has_key``
and ``api_key_last4`` for the UI to indicate whether a key is set.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LLMConfigRead(BaseModel):
    """Response for ``GET /settings/llm`` — masked, never returns the key."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="Active provider: 'fixture' or 'openai'.")
    has_api_key: bool = Field(description="Whether an API key is configured.")
    api_key_last4: str | None = Field(
        default=None, description="Last 4 chars of the stored key, or null."
    )
    base_url: str | None = None
    model: str | None = None
    temperature: float | None = None
    updated_at: str | None = None


class LLMConfigUpdate(BaseModel):
    """Request body for ``PUT /settings/llm``.

    All fields are optional. ``api_key`` empty/omitted = keep existing key.
    Set ``provider`` to ``fixture`` to use the offline deterministic planner.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, description="'fixture' or 'openai'.")
    api_key: str | None = Field(
        default=None,
        description="New API key. Empty/null = keep existing key unchanged.",
    )
    base_url: str | None = Field(default=None, description="OpenAI-compatible base URL.")
    model: str | None = Field(default=None, description="Model name e.g. 'gpt-4o-mini'.")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


__all__ = ["LLMConfigRead", "LLMConfigUpdate"]
