"""OHLCV data-quality computation (FRA-9).

Week 1 computes the report **on demand** — there is no persistence of
``data_quality_reports`` yet. Each request evaluates exactly one
``(asset, source)`` pair over a ``[start, end]`` window; multiple sources are
never mixed in a single report.

Expected trading sessions come from the asset's exchange calendar via
``exchange_calendars`` (weekends and holidays are excluded). ``coverage`` is
``observed_sessions / expected_sessions``.

Five anomaly rules are evaluated per bar (a single bar may trigger several):
``non_positive_price``, ``high_lt_low``, ``negative_volume``, ``zero_volume``,
and ``large_return`` (relative to the previous bar's close).
"""

from __future__ import annotations

from datetime import date

import exchange_calendars as xcals
import pandas as pd

from app.models.asset import Asset
from app.models.ohlcv import Ohlcv
from app.schemas.quality import AnomalyPoint, QualityReport

EXCHANGE_CALENDAR_MAP: dict[str, str] = {
    "NASDAQ": "XNAS",
    "NYSE": "XNYS",
    "AMEX": "XNYS",
    "ARCA": "XNYS",
    "XNYS": "XNYS",
    "XNAS": "XNAS",
}

# Computed once at import; the catalog of all ~102 exchange_calendars codes.
_ALL_CAL_NAMES: set[str] = set(xcals.get_calendar_names())


def calendar_code(exchange: str) -> str | None:
    """Map an asset.exchange string to an exchange_calendars code, or None.

    Known market identifiers (NASDAQ/NYSE/AMEX/ARCA) are mapped to their
    xcals codes; any string that is itself a registered xcals calendar code is
    passed through unchanged.
    """
    up = exchange.strip().upper()
    if up in EXCHANGE_CALENDAR_MAP:
        return EXCHANGE_CALENDAR_MAP[up]
    if up in _ALL_CAL_NAMES:
        return up
    return None


def expected_sessions(exchange: str, start: date, end: date) -> list[date]:
    """Trading days (excl. weekends/holidays) for ``exchange`` over [start, end].

    Raises ``ValueError`` when ``exchange`` has no known trading calendar; the
    API layer turns that into a 422.
    """
    code = calendar_code(exchange)
    if code is None:
        raise ValueError(f"no trading calendar for exchange {exchange!r}")
    cal = xcals.get_calendar(code)
    idx = cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
    return [pd.Timestamp(s).date() for s in idx]


def detect_anomalies(bars: list[Ohlcv], threshold: float = 0.2) -> list[AnomalyPoint]:
    """Run the five anomaly rules over ``bars`` (sorted ascending by time).

    A single bar may trigger multiple rules. ``large_return`` compares the
    current close against the previous bar's close and fires when the absolute
    relative move exceeds ``threshold``.
    """
    out: list[AnomalyPoint] = []
    prev_close: float | None = None
    for bar in sorted(bars, key=lambda b: b.time):
        # 1. non_positive_price — any of OHLC <= 0
        for name in ("open", "high", "low", "close"):
            v = getattr(bar, name)
            if v is not None and v <= 0:
                out.append(
                    AnomalyPoint(time=bar.time, rule="non_positive_price", detail=f"{name}={v}")
                )
        # 2. high_lt_low
        if bar.high is not None and bar.low is not None and bar.high < bar.low:
            out.append(
                AnomalyPoint(
                    time=bar.time, rule="high_lt_low", detail=f"high={bar.high} < low={bar.low}"
                )
            )
        # 3. negative_volume
        if bar.volume is not None and bar.volume < 0:
            out.append(
                AnomalyPoint(time=bar.time, rule="negative_volume", detail=f"volume={bar.volume}")
            )
        # 4. zero_volume
        if bar.volume is not None and bar.volume == 0:
            out.append(AnomalyPoint(time=bar.time, rule="zero_volume"))
        # 5. large_return (|close_t/close_{t-1} - 1| > threshold)
        if prev_close is not None and bar.close is not None and prev_close > 0:
            ret = abs(float(bar.close) / float(prev_close) - 1)
            if ret > threshold:
                out.append(
                    AnomalyPoint(time=bar.time, rule="large_return", detail=f"|return|={ret:.4f}")
                )
        if bar.close is not None:
            prev_close = float(bar.close)
    return out


def compute_quality(
    asset: Asset,
    source: str,
    start: date,
    end: date,
    bars: list[Ohlcv],
    threshold: float = 0.2,
) -> QualityReport:
    """Build a ``QualityReport`` for one (asset, source) window.

    Expected sessions come from the asset's exchange calendar; observed
    sessions are the trading days present in ``bars``. Raises ``ValueError``
    when the exchange has no known calendar (caller surfaces a 422).
    """
    expected = expected_sessions(asset.exchange, start, end)  # ValueError if no calendar
    expected_set = set(expected)
    observed_dates = {bar.time.date() for bar in bars}  # bar.time is tz-aware UTC 00:00
    observed = len(observed_dates & expected_set)
    missing = sorted(expected_set - observed_dates)
    coverage = observed / len(expected) if expected else 0.0
    return QualityReport(
        asset_id=asset.id,
        source=source,
        start=start,
        end=end,
        expected_sessions=len(expected),
        observed_sessions=observed,
        missing_sessions_count=len(missing),
        coverage=round(coverage, 6),
        missing_sessions=missing,
        anomalies=detect_anomalies(bars, threshold),
    )
