"""yfinance OHLCV fetch adapter.

Wraps :mod:`yfinance` to download daily OHLCV bars. Requests are issued with
``auto_adjust=False`` so both the raw Close and the split/dividend-adjusted
``Adj Close`` are returned. The raw Close is exposed as :attr:`OhlcvBar.close`
and the adjusted close as :attr:`OhlcvBar.adjusted_close`.

Only transient network/rate-limit errors are retried (bounded exponential
backoff). Parameter errors — e.g. a bad/unknown ``symbol`` that yields an empty
DataFrame — are *not* errors: an empty list is returned without retrying or
raising.

Daily-bar timestamps are normalized to UTC midnight of the trading day via
:func:`_to_utc_midnight` so rows line up across sources and timezones. The
``retryer`` argument is injectable so tests can pass a no-wait retry policy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import requests
import yfinance as yf
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

MAX_RETRY_ATTEMPTS = 4
MAX_BACKOFF_SECONDS = 10
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    requests.exceptions.RequestException,
    ConnectionError,
    TimeoutError,
)


@dataclass(frozen=True)
class OhlcvBar:
    """A single daily OHLCV bar normalized from a yfinance row.

    ``time`` is tz-aware UTC at the trading-day midnight. ``close`` holds the
    raw Close (``auto_adjust=False``); ``adjusted_close`` holds ``Adj Close``
    when present. ``volume`` is ``None`` for instruments that don't report it.
    """

    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal | None
    volume: int | None


def _to_utc_midnight(ts: pd.Timestamp | datetime) -> datetime:
    """Return the trading day as a tz-aware UTC datetime at 00:00.

    Daily bars are normalized to UTC midnight of the trading day so that the
    same calendar day maps to the same row regardless of the source timezone.
    """
    d = ts.date()
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _to_decimal(value: object) -> Decimal | None:
    """Coerce a (possibly NaN) scalar to :class:`~decimal.Decimal` or ``None``."""
    if pd.isna(value):
        return None
    return Decimal(str(value))


def _to_int(value: object) -> int | None:
    """Coerce a (possibly NaN) scalar to ``int`` or ``None``."""
    if pd.isna(value):
        return None
    return int(value)


def _default_retryer() -> Retrying:
    """Build the default :class:`~tenacity.Retrying` policy.

    Retries only :data:`RETRYABLE_EXCEPTIONS` with exponential backoff (capped
    at :data:`MAX_BACKOFF_SECONDS`) for up to :data:`MAX_RETRY_ATTEMPTS` tries.
    """
    return Retrying(
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        wait=wait_exponential(multiplier=1, max=MAX_BACKOFF_SECONDS),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        reraise=True,
    )


def fetch_ohlcv(
    symbol: str, start: date, end: date, retryer: Retrying | None = None
) -> list[OhlcvBar]:
    """Fetch daily OHLCV bars for ``symbol`` over ``[start, end)``.

    An unknown/empty ``symbol`` returns an empty list (no retry, no raise).
    Network and rate-limit failures are retried via ``retryer`` (the default
    policy is :func:`_default_retryer`; tests may inject a no-wait one).
    """
    retry: Callable[..., object] = retryer if retryer is not None else _default_retryer()

    def _do_fetch() -> pd.DataFrame:
        return yf.Ticker(symbol).history(
            start=start.isoformat(), end=end.isoformat(), auto_adjust=False
        )

    df = retry(_do_fetch)
    if df is None or df.empty:
        return []

    bars: list[OhlcvBar] = []
    for ts, row in df.iterrows():
        bars.append(
            OhlcvBar(
                time=_to_utc_midnight(ts),
                open=_to_decimal(row["Open"]),
                high=_to_decimal(row["High"]),
                low=_to_decimal(row["Low"]),
                close=_to_decimal(row["Close"]),
                adjusted_close=_to_decimal(row.get("Adj Close")),
                volume=_to_int(row["Volume"]),
            )
        )
    return bars
