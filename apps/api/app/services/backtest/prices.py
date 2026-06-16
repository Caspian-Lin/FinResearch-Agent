"""Backtest price-series reader — ohlcv → aligned wide DataFrame (FRA-27).

Loads a universe's price series into the wide-frame convention locked by the
FRA-25 interface contract (``docs/backtesting-methodology.md`` §接口契约):
index = tz-aware UTC-midnight trading days, columns = ``str(asset_id)``,
values = ``float`` prices.

Reuses the Week 1 ohlcv read path + ORM session and the FRA-9
``exchange_calendars`` trading-day logic. **No forward-fill** — missing bars
stay ``NaN`` so strategies/engines decide how to handle them (anti-cheat: never
silently invent data visible only in the future).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.ohlcv import Ohlcv
from app.services.backtest.types import PriceField
from app.services.quality import expected_sessions

logger = logging.getLogger(__name__)


def load_prices(
    db: Session,
    universe: Sequence[uuid.UUID],
    source: str,
    start: date,
    end: date,
    price_field: PriceField,
) -> pd.DataFrame:
    """Load aligned prices for ``universe`` over ``[start, end]`` (inclusive).

    Returns a wide ``DataFrame``: index = UTC-midnight trading days (the union
    of the universe's exchange calendars — weekends/holidays excluded), columns
    = ``str(asset_id)``, values = ``float``. ``price_field`` selects raw close
    vs adjusted close.

    Missing-data policy:
    * an asset with **no bars at all** in the window is dropped (logged at
      WARNING) — it carries no signal;
    * partial gaps stay ``NaN`` (no forward-fill);
    * a universe that ends up with **zero usable assets** raises ``ValueError``.

    Raises ``ValueError`` if any universe asset's exchange has no known trading
    calendar (surfaced from the FRA-9 ``expected_sessions`` helper) or if the
    inputs are degenerate (empty universe, ``start > end``).
    """
    if not universe:
        raise ValueError("universe must contain at least one asset_id")
    if start > end:
        raise ValueError(f"start ({start}) must be <= end ({end})")

    price_col = Ohlcv.close if price_field is PriceField.RAW else Ohlcv.adjusted_close

    # 1) Universe exchanges → union of trading days (FRA-9 exchange-calendars).
    asset_rows = db.execute(
        select(Asset.id, Asset.exchange).where(Asset.id.in_(list(universe)))
    ).all()
    exchanges = {row.exchange for row in asset_rows}
    trading_index = _trading_index(exchanges, start, end)  # ValueError if unknown exchange

    # 2) Pull ohlcv bars for the window and pivot to wide form.
    rows = db.execute(
        select(Ohlcv.asset_id, Ohlcv.time, price_col.label("price")).where(
            Ohlcv.asset_id.in_(list(universe)),
            Ohlcv.source == source,
            Ohlcv.time >= _utc_midnight(start),
            Ohlcv.time < _utc_midnight(end) + timedelta(days=1),
        )
    ).all()
    wide = pd.DataFrame(
        [(r.asset_id, r.time, r.price) for r in rows],
        columns=["asset_id", "time", "price"],
    )
    if wide.empty:
        raise ValueError(
            f"no usable price data for universe of {len(universe)} asset(s) "
            f"(source={source!r}, window=[{start}, {end}], field={price_field.value})"
        )
    wide = (
        wide.pivot(index="time", columns="asset_id", values="price").sort_index().astype("float64")
    )
    wide.columns = [str(c) for c in wide.columns]

    # 3) Align to the calendar skeleton (reindex only — NaNs stay explicit).
    wide = wide.reindex(trading_index)

    # 4) Drop fully-empty asset columns (no data at all in the window); warn.
    fully_empty = wide.columns[wide.isna().all()].tolist()
    if fully_empty:
        logger.warning(
            "dropping %d asset(s) with no bars in window: %s", len(fully_empty), fully_empty
        )
        wide = wide.drop(columns=fully_empty)

    if wide.empty:
        raise ValueError(
            f"no usable price data for universe of {len(universe)} asset(s) "
            f"(source={source!r}, window=[{start}, {end}], field={price_field.value})"
        )

    return wide


def _utc_midnight(d: date) -> datetime:
    """A date as a tz-aware UTC-midnight datetime (matches ``ohlcv.time``)."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _trading_index(exchanges: set[str], start: date, end: date) -> pd.DatetimeIndex:
    """Union of trading days across ``exchanges`` as a UTC-midnight index.

    Reuses the FRA-9 ``expected_sessions`` helper (maps each exchange to its
    ``exchange_calendars`` code; raises ``ValueError`` on an unknown exchange).
    """
    days: set[date] = set()
    for exchange in exchanges:
        days.update(expected_sessions(exchange, start, end))
    return pd.DatetimeIndex(pd.Timestamp(d, tz="UTC") for d in sorted(days))
