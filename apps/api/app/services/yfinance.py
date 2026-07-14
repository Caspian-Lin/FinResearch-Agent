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

As of FRA-23 :class:`OhlcvBar` and the coercion/retry helpers live in
:mod:`app.services.datasources.base` and are shared by every source adapter;
they are re-exported here (under their original names) so existing callers —
the upsert service and the ingestion tests — keep importing from this module
unchanged. This module also exposes :func:`fetch_ohlcv`, the free-function form
the yfinance adapter was originally written as; the pluggable
:class:`~app.services.datasources.base.DataSource` wrapper sits in
:mod:`app.services.datasources`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pandas as pd
import yfinance as yf
from tenacity import Retrying

# Shared bar type + coercion/retry helpers (FRA-23). Re-exported here under the
# historical names so this module's public surface is unchanged.
from app.services.datasources.base import (
    MAX_BACKOFF_SECONDS,
    MAX_RETRY_ATTEMPTS,
    RETRYABLE_EXCEPTIONS,
    OhlcvBar,
    build_default_retryer,
    to_decimal,
    to_int,
    to_utc_midnight,
)

# Definitions moved to .datasources.base (FRA-23). Listed in __all__ so ruff
# treats them as a public re-export (not unused imports) and existing imports
# from this module — `OhlcvBar`, `RETRYABLE_EXCEPTIONS`, the private `_to_*`
# aliases below, and `fetch_ohlcv` — keep working unchanged.
__all__ = [
    "MAX_BACKOFF_SECONDS",
    "MAX_RETRY_ATTEMPTS",
    "OhlcvBar",
    "RETRYABLE_EXCEPTIONS",
    "fetch_ohlcv",
]

# Backward-compatible private aliases — tests import ``_to_utc_midnight`` etc.
_to_utc_midnight = to_utc_midnight
_to_decimal = to_decimal
_to_int = to_int


def _default_retryer() -> Retrying:
    """Build the default :class:`~tenacity.Retrying` policy (shared)."""
    return build_default_retryer()


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
