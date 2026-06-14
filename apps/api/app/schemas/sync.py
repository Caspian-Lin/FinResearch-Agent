"""Pydantic schemas for the OHLCV sync API (FRA-8)."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class SyncRequest(BaseModel):
    """Payload for ``POST /sync``."""

    model_config = ConfigDict(extra="forbid")

    asset_id: uuid.UUID
    start: date
    end: date
    source: str = Field(default="yfinance")


class SyncEnqueueResponse(BaseModel):
    """202 response after a sync job is enqueued."""

    job_id: str
    status: str = "pending"
    asset_id: uuid.UUID
    start: date
    end: date
    source: str


class SyncJobStatus(BaseModel):
    """Lifecycle + inputs + outcome for a sync job (GET /sync/{job_id})."""

    job_id: str
    status: str  # pending | running | success | failed
    asset_id: uuid.UUID | None = None
    start: date | None = None
    end: date | None = None
    source: str | None = None
    inserted: int | None = None
    updated: int | None = None
    error: dict[str, str] | None = None  # {"type": ..., "message": ...}
