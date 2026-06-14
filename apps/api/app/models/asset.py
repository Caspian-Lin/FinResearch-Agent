"""Asset ORM model — tradeable instrument metadata (stocks, ETFs, indices).

Week 1 data foundation. Symbol is the natural primary key; OHLCV bars and
watchlist items reference assets by symbol.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Asset(Base):
    """A tradeable instrument tracked by the system (e.g. ``AAPL``, ``SPY``)."""

    __tablename__ = "assets"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
