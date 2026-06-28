"""Tushare OHLCV adapter (FRA-23) — token-gated, high-quality A-share source.

Tushare Pro is the highest-quality public A-share feed (adjustment, financials,
index constituents) but requires a registered token (https://tushare.pro) and
rate-limits per points tier. The token is injected via ``settings.tushare_token``
(read from ``TUSHARE_TOKEN``) — never a bare ``os.getenv``.

Like AkShare, ``tushare`` is an *optional* dependency
(``uv sync --extra data-cn``) imported lazily inside
:meth:`TushareSource.fetch_ohlcv`, so the module imports cleanly and the app
starts even when the library (or token) is absent.

Adjustment: ``pro.daily`` returns *unadjusted* OHLCV; the adjusted series needs
``pro_bar`` which has a higher points threshold. We therefore populate
``close`` with the unadjusted close and leave ``adjusted_close=None`` so callers
fall back to ``adjusted_close ?? close`` honestly, rather than pretending an
adjusted series exists. (Forward/back-adjusted switch is a later issue.)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd
from tenacity import Retrying

from app.services.datasources.base import (
    OhlcvBar,
    build_default_retryer,
    to_decimal,
    to_int,
    to_utc_midnight,
)

# Tushare ``pro.daily`` volume (``vol``) is in 手 (lots of 100 shares); stored
# raw with the unit documented, same convention as the AkShare adapter.


class TushareSource:
    """Tushare Pro data source — token required, A-share daily bars.

    Constructing without a token raises immediately so misconfiguration surfaces
    at dispatch time (and the sync job fails loudly) rather than as a silent
    zero-bar "success".
    """

    name = "tushare"

    def __init__(self, token: str, retryer: Retrying | None = None) -> None:
        if not token or not token.strip():
            raise ValueError(
                "TUSHARE_TOKEN is not configured; set it in .env to use the tushare source"
            )
        self._token = token
        self._retryer = retryer
        self._pro: Any = None  # lazily built pro_api client (Any under ignore_missing_imports)

    def _client(self) -> Any:
        """Build (once) the Tushare Pro client via lazy import + set_token."""
        if self._pro is None:
            import tushare as ts  # lazy: optional dependency

            ts.set_token(self._token)
            self._pro = ts.pro_api()
        return self._pro

    def fetch_ohlcv(self, symbol: str, start: date, end: date) -> list[OhlcvBar]:
        """Fetch unadjusted daily A-share bars for ``symbol`` over ``[start, end]``.

        Only A-shares (``.SH``/``.SZ``/``.BJ`` suffix) are supported; other
        symbols raise :class:`ValueError`. An empty result (delisted / pre-IPO
        window / points gating) returns ``[]``.
        """
        ts_code = _map_tushare_symbol(symbol)
        retry: Callable[..., object] = (
            self._retryer if self._retryer is not None else build_default_retryer()
        )

        def _do_fetch() -> pd.DataFrame:
            pro = self._client()
            return pro.daily(
                ts_code=ts_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )

        df = retry(_do_fetch)
        if df is None or df.empty:
            return []

        # pro.daily returns newest-first; sort ascending for a stable series.
        df = df.sort_values("trade_date")

        bars: list[OhlcvBar] = []
        for _, row in df.iterrows():
            bars.append(
                OhlcvBar(
                    time=to_utc_midnight(pd.Timestamp(str(row["trade_date"]))),
                    open=to_decimal(row["open"]),
                    high=to_decimal(row["high"]),
                    low=to_decimal(row["low"]),
                    close=to_decimal(row["close"]),  # unadjusted
                    adjusted_close=None,  # pro_bar (qfq) needs higher points tier
                    volume=to_int(row["vol"]),
                )
            )
        return bars


def _map_tushare_symbol(symbol: str) -> str:
    """Map a canonical A-share symbol to the Tushare ``ts_code`` form.

    ``600519.SH`` / ``000001.SZ`` / ``430017.BJ`` pass through unchanged —
    Tushare Pro uses uppercase ``.SH``/``.SZ``/``.BJ`` suffixes natively, which
    matches the unified exchange-suffix convention (FRA-78). Non-A-share symbols
    are rejected with :class:`ValueError`.
    """
    if symbol.endswith((".SH", ".SZ", ".BJ")):
        return symbol
    raise ValueError(f"tushare adapter supports A-shares only (.SH/.SZ/.BJ suffix); got {symbol!r}")
