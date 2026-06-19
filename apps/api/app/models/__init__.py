"""SQLAlchemy ORM models.

Importing this package surfaces every model so Alembic autogenerate sees them
via ``Base.metadata`` (see ``infra/migrations/env.py``).
"""

from __future__ import annotations

from app.models.asset import Asset
from app.models.ohlcv import Ohlcv
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem

__all__ = ["Asset", "Ohlcv", "User", "Watchlist", "WatchlistItem"]
