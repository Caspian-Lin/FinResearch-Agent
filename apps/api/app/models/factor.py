"""Factor value ORM model — TimescaleDB hypertable, partitioned by ``time``.

Factor values are append-oriented time series derived from market data. The
``factor_name`` encodes the factor and its parameters (for example
``momentum_21`` or ``rsi_14``), while ``source`` identifies the computation
pipeline/version that produced the value.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FactorValue(Base):
    """Computed factor value for one asset at one timestamp."""

    __tablename__ = "factor_values"
    __table_args__ = (
        Index("ix_factor_values_factor_name_time", "factor_name", "time"),
        Index("ix_factor_values_asset_id_time", "asset_id", "time"),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id"), primary_key=True
    )
    factor_name: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    source: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
