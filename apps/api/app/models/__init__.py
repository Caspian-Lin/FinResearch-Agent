"""SQLAlchemy ORM models.

Importing this package surfaces every model so Alembic autogenerate sees them
via ``Base.metadata`` (see ``infra/migrations/env.py``).
"""

from __future__ import annotations

from app.models.asset import Asset
from app.models.backtest import (
    BacktestMetrics,
    BacktestRun,
    EquityCurvePoint,
    Trade,
)
from app.models.factor import FactorValue
from app.models.news import NewsItem, SentimentScore
from app.models.ohlcv import Ohlcv
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem

__all__ = [
    "Asset",
    "BacktestMetrics",
    "BacktestRun",
    "EquityCurvePoint",
    "FactorValue",
    "NewsItem",
    "Ohlcv",
    "SentimentScore",
    "Trade",
    "User",
    "Watchlist",
    "WatchlistItem",
]
