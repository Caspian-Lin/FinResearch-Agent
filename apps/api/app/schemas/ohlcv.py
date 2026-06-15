"""Pydantic v2 schemas for the OHLCV read API (FRA-15).

Backend contract for OHLCV bars; the web client should reuse these field
names rather than redefining them (frontend TS bindings are a separate task).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OhlcvRead(BaseModel):
    """One OHLCV bar (read shape).

    Price fields are typed ``float`` (not ``Decimal``) so they serialize as JSON
    numbers — the frontend chart needs numeric values, and Pydantic v2 otherwise
    serializes ``Decimal`` as a string. Precision loss to float64 is acceptable
    for charting; the DB column stays ``numeric`` for storage accuracy.
    """

    model_config = ConfigDict(from_attributes=True)

    asset_id: uuid.UUID
    time: datetime
    source: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    adjusted_close: float | None
    volume: int | None


class OhlcvPage(BaseModel):
    """Cursor-paginated OHLCV page."""

    items: list[OhlcvRead]
    next_cursor: str | None = None
    has_more: bool = False
