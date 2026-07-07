"""Shared helpers for news providers (FRA-67).

Providers are pure data sources — they never touch the DB. This module owns the
value-coercion and window-filter helpers every news provider reuses, mirroring
the role :mod:`app.services.datasources.base` plays for OHLCV adapters. It
deliberately imports no concrete source library so the package stays
import-cheap and an uninstalled optional source never breaks app/worker
startup — adapters lazy-import their own library inside ``fetch``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.services.sentiment.types import NewsItem


def coerce_published_at(value: object) -> datetime:
    """Coerce a source-native publish timestamp to a tz-aware datetime.

    yfinance exposes ``providerPublishTime`` as either a Unix epoch (int/float,
    seconds) or an ISO-8601 string depending on the library version; RSS feeds
    vary similarly. A naive datetime is assumed UTC — news timestamps carry no
    reliable source timezone, and UTC is the storage convention per FRA-66.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, bool):
        # bool is a subclass of int — reject explicitly before the int branch.
        raise TypeError("unsupported published_at type: bool")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    raise TypeError(f"unsupported published_at type: {type(value).__name__}")


def filter_window(items: Sequence[NewsItem], start: datetime, end: datetime) -> list[NewsItem]:
    """Keep only items with ``published_at`` inside the half-open ``[start, end)``.

    The FRA-65 ``NewsProvider`` contract (``protocols.py:22-24``) requires
    ``[start, end)`` semantics — distinct from OHLCV's inclusive ``[start, end]``
    window. Missing coverage (an asset with no in-window items) surfaces as an
    empty list, never a synthesized row: callers must preserve the gap instead
    of forward-filling sentiment.
    """
    return [it for it in items if start <= it.published_at < end]
