"""Asset ORM model — tradeable instrument metadata (stocks, ETFs, indices).

Week 1 data foundation. Uses a surrogate UUID primary key; the natural key
(symbol, exchange) is enforced via a unique constraint since the same symbol
can appear on different exchanges.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Asset(Base):
    """A tradeable instrument tracked by the system (e.g. ``AAPL`` on NASDAQ)."""

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("symbol", "exchange", name="uq_asset_symbol_exchange"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    # Preferred data source for this asset (FRA-78): the source key the worker
    # uses by default when syncing OHLCV. Lives on the asset so the watchlist
    # can show "which source feeds this instrument" without a separate join, and
    # so seeding can pin A-shares→akshare/tushare, overseas→yfinance. The
    # OHLCV table still allows other sources to coexist per its (asset_id, time,
    # source) key — this is only the *default/preferred* one.
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="yfinance")
    # Listing lifecycle (FRA-78): active / suspended / delisted. Lets the dynamic
    # universe sync (FRA-79) mark delisted/suspended instruments in place rather
    # than deleting them (preserving historical OHLCV + watchlist references).
    list_status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
