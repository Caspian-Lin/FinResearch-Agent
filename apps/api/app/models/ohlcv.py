"""OHLCV bar ORM model — TimescaleDB hypertable, partitioned by ``time``.

The table is converted to a hypertable via ``create_hypertable()`` inside the
Alembic migration (see ``infra/migrations/versions``). Composite primary key
``(symbol, time)`` satisfies the hypertable requirement that the partitioning
column be part of the (composite) primary key.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Ohlcv(Base):
    """Open/high/low/close/volume market bar for one asset at one timestamp."""

    __tablename__ = "ohlcv"

    symbol: Mapped[str] = mapped_column(String(32), ForeignKey("assets.symbol"), primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    high: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    low: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
