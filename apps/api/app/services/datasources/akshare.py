"""AkShare OHLCV adapter (FRA-23) — free, no-token A-share fallback.

AkShare wraps public Eastmoney/Sina pages, so it needs no token and has no
official rate limit, but it can hit anti-scraping throttling (hence the shared
retry policy). Coverage is broad (A/H/US/futures/macro); this adapter targets
A-share daily bars, which is the seed universe it has to serve. Symbols follow
the unified exchange-suffix convention (FRA-78): A-shares carry ``.SH``/``.SZ``
/``.BJ`` (the legacy yfinance ``.SS`` form is retired).

AkShare is an *optional* dependency (``uv sync --extra data-cn``) and is
imported lazily inside :meth:`AkshareSource.fetch_ohlcv`, so an environment
without it still imports this module and starts the app — only actually syncing
from ``akshare`` requires the library.

Adjustment: AkShare's ``stock_zh_a_hist`` returns one adjustment regime per
call. We request ``adjust="qfq"`` (forward-adjusted) — the regime A-share
research overwhelmingly wants — and set both ``close`` and ``adjusted_close`` to
it. Exposing unadjusted-vs-adjusted as separate fields / a switch is left to a
later issue (see FRA-23 "前复权 vs 后复权开关").
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pandas as pd
from tenacity import Retrying

from app.services.datasources.base import (
    OhlcvBar,
    build_default_retryer,
    to_decimal,
    to_int,
    to_utc_midnight,
)

# AkShare's ``stock_zh_a_hist`` returns Chinese column names whose exact form
# varies across versions (some append 价, some include a 股票代码 column). Map
# each logical field to candidate names and pick whichever the frame exposes.
_COLUMN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "time": ("日期",),
    "open": ("开盘", "开盘价"),
    "close": ("收盘", "收盘价"),
    "high": ("最高", "最高价"),
    "low": ("最低", "最低价"),
    "volume": ("成交量",),
}

# AkShare volume is reported in 手 (lots of 100 shares); we store the raw value
# unchanged and document the unit rather than assume a conversion factor.


class AkshareSource:
    """AkShare data source — free, token-less A-share daily bars."""

    name = "akshare"

    def __init__(self, retryer: Retrying | None = None) -> None:
        self._retryer = retryer

    def fetch_ohlcv(self, symbol: str, start: date, end: date) -> list[OhlcvBar]:
        """Fetch forward-adjusted daily A-share bars for ``symbol``.

        Only A-shares (``.SH``/``.SZ``/``.BJ`` suffix) are supported; any other
        symbol raises :class:`ValueError` rather than silently returning no data,
        since that signals a caller/source mismatch. An empty result (delisted /
        pre-IPO window) returns ``[]`` without raising.
        """
        ak_sym = _map_a_share_symbol(symbol)
        retry: Callable[..., object] = (
            self._retryer if self._retryer is not None else build_default_retryer()
        )

        def _do_fetch() -> pd.DataFrame:
            import akshare as ak  # lazy: optional dependency, anti-scrape lib

            return ak.stock_zh_a_hist(
                symbol=ak_sym,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )

        df = retry(_do_fetch)
        if df is None or df.empty:
            return []

        cols = {field: _pick_column(df, names) for field, names in _COLUMN_CANDIDATES.items()}

        bars: list[OhlcvBar] = []
        for _, row in df.iterrows():
            bars.append(
                OhlcvBar(
                    time=to_utc_midnight(pd.Timestamp(row[cols["time"]])),
                    open=to_decimal(row[cols["open"]]),
                    high=to_decimal(row[cols["high"]]),
                    low=to_decimal(row[cols["low"]]),
                    close=to_decimal(row[cols["close"]]),
                    # qfq is the only regime requested, so adjusted == raw close.
                    adjusted_close=to_decimal(row[cols["close"]]),
                    volume=to_int(row[cols["volume"]]),
                )
            )
        return bars


def _map_a_share_symbol(symbol: str) -> str:
    """Map a canonical A-share symbol to the AkShare ``sh/sz/bj`` code form.

    ``600519.SH`` → ``sh600519``; ``000001.SZ`` → ``sz000001``;
    ``430017.BJ`` → ``bj430017``. The suffix encodes the exchange (SSE→sh,
    SZSE→sz, BSE→bj) per the unified exchange-suffix convention (FRA-78, which
    retires the legacy yfinance ``.SS`` form). Non-A-share symbols are rejected
    with :class:`ValueError`.
    """
    suffix_to_prefix = {".SH": "sh", ".SZ": "sz", ".BJ": "bj"}
    for suffix, prefix in suffix_to_prefix.items():
        if symbol.endswith(suffix):
            return prefix + symbol[: -len(suffix)]
    raise ValueError(
        f"akshare adapter supports A-shares only (.SH/.SZ/.BJ suffix); got {symbol!r}"
    )


def _pick_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str:
    """Return the first candidate column name present in ``df``.

    AkShare column wording drifts between releases; this lets the adapter track
    it without hard-coding one spelling. Raises :class:`KeyError` if none match
    — a genuine schema break worth surfacing rather than masking.
    """
    for name in candidates:
        if name in df.columns:
            return name
    raise KeyError(
        f"none of AkShare columns {candidates} found in frame columns {list(df.columns)}"
    )
