"""Pydantic v2 schemas for the Asset resource.

Identity is the surrogate ``asset_id`` UUID; ``symbol`` is *not* globally
unique (the same ticker can trade on different exchanges), so consumers
must always address an asset by its UUID.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AssetCreate(BaseModel):
    """Payload for ``POST /assets``.

    ``symbol`` and ``exchange`` are normalized to a trimmed, upper-cased
    form on the server, so callers may pass either case here.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    symbol: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=255)
    exchange: str = Field(..., min_length=1, max_length=64)
    asset_type: str = Field(..., min_length=1, max_length=32)
    currency: str = Field(..., min_length=1, max_length=8)


class AssetRead(BaseModel):
    """Outbound representation of a stored asset.

    The ORM column is ``id``; we expose it as ``asset_id`` in the JSON body
    to make the UUID identity unambiguous in API responses.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID = Field(..., serialization_alias="asset_id")
    symbol: str
    name: str
    exchange: str
    asset_type: str
    currency: str
    # Preferred source + listing lifecycle (FRA-78). Exposed so the frontend can
    # show the per-asset source and filter/hide delisted instruments.
    data_source: str
    list_status: str
    created_at: datetime


class AssetPage(BaseModel):
    """Stable pagination envelope for ``GET /assets``.

    Ordering is deterministic (symbol, exchange, id) so paging via
    ``limit``/``offset`` is stable across requests even if rows are inserted
    concurrently.
    """

    items: list[AssetRead]
    total: int
    limit: int
    offset: int
