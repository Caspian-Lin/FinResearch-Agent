"""Pluggable data-source abstraction (FRA-23).

The historical-price pipeline was originally hard-wired to yfinance
(:mod:`app.services.yfinance`). FRA-23 turns "a place bars come from" into a
swappable layer so AkShare / Tushare (domestic A-share sources) can be added
without touching the worker or the API.

This module is the seam: it owns the shared bar type (:class:`OhlcvBar`), the
:class:`DataSource` protocol every adapter satisfies, and the value-coercion +
retry helpers all adapters reuse. It deliberately imports *no* concrete source
library (akshare/tushare/yfinance) so the package stays import-cheap and so an
uninstalled optional source never breaks app/worker startup — adapters
lazy-import their own library inside :meth:`DataSource.fetch_ohlcv`.

The :class:`OhlcvBar` and coercion helpers used to live in
:mod:`app.services.yfinance`; they were hoisted here so all three sources share
one definition. :mod:`app.services.yfinance` re-exports them for backward
compatibility (existing tests and the upsert service import them from there).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

import pandas as pd
import requests
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Shared retry policy. Bounded exponential backoff, only for transient
# network/rate-limit failures — never for "symbol returned nothing" (that is a
# parameter result, not a retryable error, and every adapter returns [] for it).
MAX_RETRY_ATTEMPTS = 4
MAX_BACKOFF_SECONDS = 10
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    requests.exceptions.RequestException,
    ConnectionError,
    TimeoutError,
)


@dataclass(frozen=True)
class OhlcvBar:
    """A single daily OHLCV bar normalized from one source row.

    ``time`` is tz-aware UTC at the trading-day midnight. ``close`` is the
    unadjusted Close when the source distinguishes (yfinance ``auto_adjust=
    False``); ``adjusted_close`` is the split/dividend-adjusted close when the
    source provides it, else ``None``. ``volume`` is ``None`` for instruments
    that don't report it.
    """

    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal | None
    volume: int | None


class DataSource(Protocol):
    """A pluggable provider of daily OHLCV bars.

    Adapters map the canonical ``(symbol, start, end)`` request to their
    underlying library and return normalized :class:`OhlcvBar` rows. The
    signature matches the original ``app.services.yfinance.fetch_ohlcv`` so the
    yfinance adapter is a thin wrapper with no behavior change.

    An unknown / empty symbol is *not* an error: adapters return ``[]``. Only
    transient network / rate-limit failures are retried (inside the adapter) and
    only a genuinely broken call raises.
    """

    #: Stable key used in the ``ohlcv.source`` column and the API allow-list.
    name: str

    def fetch_ohlcv(self, symbol: str, start: date, end: date) -> list[OhlcvBar]:
        """Return daily bars for ``symbol`` over the inclusive ``[start, end]``."""
        ...


def to_utc_midnight(ts: pd.Timestamp | datetime) -> datetime:
    """Return the trading day as a tz-aware UTC datetime at 00:00.

    Daily bars are normalized to UTC midnight of the trading day so the same
    calendar day maps to the same row regardless of the source timezone.
    """
    d = ts.date()
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def to_decimal(value: object) -> Decimal | None:
    """Coerce a (possibly NaN) scalar to :class:`~decimal.Decimal` or ``None``."""
    if pd.isna(value):
        return None
    return Decimal(str(value))


def to_int(value: object) -> int | None:
    """Coerce a (possibly NaN) scalar to ``int`` or ``None``."""
    if pd.isna(value):
        return None
    return int(value)


def build_default_retryer() -> Retrying:
    """Build the shared :class:`~tenacity.Retrying` policy.

    Retries only :data:`RETRYABLE_EXCEPTIONS` with exponential backoff (capped
    at :data:`MAX_BACKOFF_SECONDS`) for up to :data:`MAX_RETRY_ATTEMPTS` tries.
    Adapters accept an injectable retryer so tests can pass a no-wait policy.
    """
    return Retrying(
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        wait=wait_exponential(multiplier=1, max=MAX_BACKOFF_SECONDS),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        reraise=True,
    )
