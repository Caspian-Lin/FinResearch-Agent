"""Pydantic v2 schemas for the Watchlist resource.

A watchlist is a named, user-owned collection of assets. Identity is the
surrogate ``watchlist_id`` UUID. Items are addressed by their ``asset_id``
UUID and are hydrated with the joined ``Asset`` metadata (symbol, exchange,
name) so consumers can render a watchlist in a single round trip.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WatchlistCreate(BaseModel):
    """Payload for ``POST /watchlists``.

    The name is trimmed of surrounding whitespace; a name that trims to the
    empty string fails ``min_length`` validation (422). ``extra="forbid"``
    rejects unknown keys so clients get a tight contract.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)


class WatchlistItemRead(BaseModel):
    """A single member of a watchlist, hydrated with asset metadata.

    ``asset_id`` is the identity key (matches the ``Asset`` surrogate UUID);
    ``symbol``/``exchange``/``name`` are joined from the ``assets`` table.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    asset_id: uuid.UUID
    symbol: str
    exchange: str
    name: str
    data_source: str
    added_at: datetime


class WatchlistRead(BaseModel):
    """Outbound representation of a stored watchlist.

    The ORM column is ``id``; we expose it as ``watchlist_id`` in the JSON
    body to keep the UUID identity unambiguous in API responses (mirrors the
    ``AssetRead`` convention).
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID = Field(..., serialization_alias="watchlist_id")
    name: str
    created_at: datetime
    items: list[WatchlistItemRead] = Field(default_factory=list)
