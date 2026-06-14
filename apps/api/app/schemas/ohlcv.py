"""Pydantic v2 schemas for the OHLCV read API (FRA-15).

Backend contract for OHLCV bars; the web client should reuse these field
names rather than redefining them (frontend TS bindings are a separate task).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class OhlcvRead(BaseModel):
    """One OHLCV bar (read shape)."""

    model_config = ConfigDict(from_attributes=True)

    asset_id: uuid.UUID
    time: datetime
    source: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    adjusted_close: Decimal | None
    volume: int | None


class OhlcvPage(BaseModel):
    """Cursor-paginated OHLCV page."""

    items: list[OhlcvRead]
    next_cursor: str | None = None
    has_more: bool = False
