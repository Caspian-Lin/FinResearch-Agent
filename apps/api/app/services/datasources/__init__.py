"""Pluggable data-source registry + dispatcher (FRA-23).

The single entry point :func:`get_data_source` routes a source key to the
matching :class:`~app.services.datasources.base.DataSource` adapter. New sources
are added by registering a factory here — the worker and API read
:data:`SUPPORTED_SOURCES` from this module, so adding a source needs no change
outside it.

Three sources ship today:

* ``yfinance`` — overseas equities/ETFs; the original adapter, wrapped as a
  :class:`DataSource` with no behavior change.
* ``akshare`` — free, token-less A-share fallback (:mod:`.akshare`).
* ``tushare`` — token-gated, high-quality A-share feed (:mod:`.tushare`).

The Tushare token is read from ``settings.tushare_token`` inside its factory, so
a missing token surfaces as a clear error only when ``tushare`` is actually
dispatched — never at import time.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from tenacity import Retrying

from app.core.config import settings
from app.services.datasources.akshare import AkshareSource
from app.services.datasources.base import DataSource, OhlcvBar
from app.services.datasources.tushare import TushareSource
from app.services.yfinance import fetch_ohlcv as _yf_fetch_ohlcv

__all__ = [
    "AkshareSource",
    "DataSource",
    "OhlcvBar",
    "SUPPORTED_SOURCES",
    "TushareSource",
    "YfinanceSource",
    "get_data_source",
]


class YfinanceSource:
    """:class:`DataSource` wrapper over the original :func:`fetch_ohlcv`.

    A pure delegation adapter: it preserves the existing yfinance behavior
    (auto_adjust=False, raw Close→close, Adj Close→adjusted_close) so routing
    through the dispatcher changes nothing for yfinance callers.
    """

    name = "yfinance"

    def __init__(self, retryer: Retrying | None = None) -> None:
        self._retryer = retryer

    def fetch_ohlcv(self, symbol: str, start: date, end: date) -> list[OhlcvBar]:
        return _yf_fetch_ohlcv(symbol, start, end, retryer=self._retryer)


# Source key → zero-arg factory. Reading the Tushare token lazily (inside the
# factory) means a missing token is reported only when tushare is dispatched.
_FACTORIES: dict[str, Callable[[], DataSource]] = {
    "yfinance": lambda: YfinanceSource(),
    "akshare": lambda: AkshareSource(),
    "tushare": lambda: TushareSource(token=settings.tushare_token),
}

# Derived from the registry so the allow-list can never drift from the adapters.
SUPPORTED_SOURCES: tuple[str, ...] = tuple(_FACTORIES.keys())


def get_data_source(source: str) -> DataSource:
    """Return the :class:`DataSource` adapter for ``source``.

    Raises :class:`ValueError` for an unknown source so the caller (worker /
    API) can surface it as an input/config error rather than a silent miss.
    """
    factory = _FACTORIES.get(source)
    if factory is None:
        raise ValueError(f"unsupported source: {source!r}; expected one of {SUPPORTED_SOURCES}")
    return factory()
