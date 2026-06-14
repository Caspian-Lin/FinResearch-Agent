"""Watchlist ORM models — user-defined asset collections."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Watchlist(Base):
    """A named collection of assets owned by a user."""

    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WatchlistItem(Base):
    """Association between a watchlist and an asset (by symbol)."""

    __tablename__ = "watchlist_items"

    watchlist_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("watchlist.id"), primary_key=True
    )
    symbol: Mapped[str] = mapped_column(String(32), ForeignKey("assets.symbol"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
