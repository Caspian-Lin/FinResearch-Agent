"""Real-DB tests for the backtest price-series reader (FRA-27).

``load_prices`` turns a universe's ohlcv bars into the FRA-25 wide-frame
convention. These tests pin: UTC-midnight trading-day alignment (NASDAQ
calendar, weekends/holidays excluded), raw vs adjusted field selection,
partial-gap NaNs (no forward-fill), all-null column drop + warning, and the
degenerate-input / no-data error paths.

Host Postgres is used directly with surgical cleanup scoped to the ``FRA27TEST``
prefix; ``conftest.py`` is left untouched (mirrors ``test_ohlcv_ingestion.py``).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.ohlcv import Ohlcv
from app.services.backtest import load_prices
from app.services.backtest.types import PriceField
from sqlalchemy import text
from sqlalchemy.orm import Session

PREFIX = "FRA27TEST"


# ---------------------------------------------------------------------------
# DB helpers + fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    """Delete only ohlcv/asset rows owned by this suite."""
    db.execute(
        text("DELETE FROM ohlcv WHERE asset_id IN (SELECT id FROM assets WHERE symbol LIKE :p)"),
        {"p": f"{PREFIX}%"},
    )
    db.execute(text("DELETE FROM assets WHERE symbol LIKE :p"), {"p": f"{PREFIX}%"})
    db.commit()


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)
        db.close()


def _make_asset(db: Session, symbol: str, exchange: str = "NASDAQ") -> Asset:
    asset = Asset(
        symbol=symbol,
        name=f"Test {symbol}",
        exchange=exchange,
        asset_type="stock",
        currency="USD",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _add_bar(
    db: Session,
    asset_id: object,
    day: str,
    close: int,
    adjusted_close: int | None,
    source: str = "yfinance",
) -> None:
    d = date.fromisoformat(day)
    db.add(
        Ohlcv(
            asset_id=asset_id,
            time=datetime(d.year, d.month, d.day, tzinfo=UTC),
            source=source,
            open=Decimal(str(close)),
            high=Decimal(str(close)),
            low=Decimal(str(close)),
            close=Decimal(str(close)),
            adjusted_close=Decimal(str(adjusted_close)) if adjusted_close is not None else None,
            volume=1000,
        )
    )


# ---------------------------------------------------------------------------
# alignment + field selection
# ---------------------------------------------------------------------------


def test_load_prices_single_asset_adjusted_aligned(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA27TEST-A")
    for day, c, a in [
        ("2024-01-02", 100, 99),
        ("2024-01-03", 102, 101),
        ("2024-01-04", 104, 103),
        ("2024-01-05", 106, 105),
    ]:
        _add_bar(db_session, asset.id, day, c, a)
    db_session.commit()

    df = load_prices(
        db_session, [asset.id], "yfinance", date(2024, 1, 2), date(2024, 1, 5), PriceField.ADJUSTED
    )

    # trading-day index: 01-02..05 are all NASDAQ sessions (no holiday); the
    # preceding Monday 01-01 (New Year) and 01-06/07 (weekend) are excluded.
    # Compare by date (not assert_index_equal) to ignore pandas' s-vs-us dtype
    # precision — the instants are identical.
    assert [ts.date() for ts in df.index] == [
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
        date(2024, 1, 5),
    ]
    assert str(df.index.tz) == "UTC"  # tz-aware UTC, per the wide-frame convention
    assert list(df.columns) == [str(asset.id)]
    assert df[str(asset.id)].tolist() == [99.0, 101.0, 103.0, 105.0]


def test_load_prices_raw_field_uses_close_not_adjusted(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA27TEST-RAW")
    _add_bar(db_session, asset.id, "2024-01-02", 100, 99)
    _add_bar(db_session, asset.id, "2024-01-03", 102, 101)
    db_session.commit()

    df = load_prices(
        db_session, [asset.id], "yfinance", date(2024, 1, 2), date(2024, 1, 3), PriceField.RAW
    )
    assert df[str(asset.id)].tolist() == [100.0, 102.0]  # raw close, not adjusted


# ---------------------------------------------------------------------------
# multi-asset alignment: partial gaps stay NaN (no forward-fill)
# ---------------------------------------------------------------------------


def test_load_prices_multi_asset_partial_gap_is_nan(db_session: Session) -> None:
    a = _make_asset(db_session, "FRA27TEST-M1")
    b = _make_asset(db_session, "FRA27TEST-M2")
    for day, c in [
        ("2024-01-02", 100),
        ("2024-01-03", 102),
        ("2024-01-04", 104),
        ("2024-01-05", 106),
    ]:
        _add_bar(db_session, a.id, day, c, c)
    # b only has the first two days -> 01-04/05 are a partial gap
    _add_bar(db_session, b.id, "2024-01-02", 50, 50)
    _add_bar(db_session, b.id, "2024-01-03", 52, 52)
    db_session.commit()

    df = load_prices(
        db_session,
        [a.id, b.id],
        "yfinance",
        date(2024, 1, 2),
        date(2024, 1, 5),
        PriceField.ADJUSTED,
    )
    assert set(df.columns) == {str(a.id), str(b.id)}
    assert len(df) == 4

    d4 = pd.Timestamp("2024-01-04", tz="UTC")
    assert df.loc[d4, str(a.id)] == 104.0
    assert pd.isna(df.loc[d4, str(b.id)])  # gap, not forward-filled
    assert pd.isna(df.loc[pd.Timestamp("2024-01-05", tz="UTC"), str(b.id)])


def test_load_prices_drops_asset_with_all_null_prices(db_session: Session) -> None:
    a = _make_asset(db_session, "FRA27TEST-D1")
    b = _make_asset(db_session, "FRA27TEST-D2")
    _add_bar(db_session, a.id, "2024-01-02", 100, 100)
    _add_bar(db_session, a.id, "2024-01-03", 102, 102)
    # b has bars but adjusted_close is NULL -> all-NaN column under ADJUSTED
    _add_bar(db_session, b.id, "2024-01-02", 50, None)
    _add_bar(db_session, b.id, "2024-01-03", 52, None)
    db_session.commit()

    df = load_prices(
        db_session,
        [a.id, b.id],
        "yfinance",
        date(2024, 1, 2),
        date(2024, 1, 3),
        PriceField.ADJUSTED,
    )
    assert list(df.columns) == [str(a.id)]  # b dropped (no usable adjusted data)
    assert str(b.id) not in df.columns


# ---------------------------------------------------------------------------
# error paths
# ---------------------------------------------------------------------------


def test_load_prices_empty_universe_raises(db_session: Session) -> None:
    with pytest.raises(ValueError, match="universe"):
        load_prices(
            db_session, [], "yfinance", date(2024, 1, 2), date(2024, 1, 5), PriceField.ADJUSTED
        )


def test_load_prices_start_after_end_raises(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA27TEST-SE")
    with pytest.raises(ValueError, match="start"):
        load_prices(
            db_session,
            [asset.id],
            "yfinance",
            date(2024, 1, 5),
            date(2024, 1, 2),
            PriceField.ADJUSTED,
        )


def test_load_prices_all_missing_raises(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA27TEST-AM")  # exists but has zero bars
    with pytest.raises(ValueError, match="no usable price data"):
        load_prices(
            db_session,
            [asset.id],
            "yfinance",
            date(2024, 1, 2),
            date(2024, 1, 5),
            PriceField.ADJUSTED,
        )
