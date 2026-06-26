"""Real-DB tests for the factor computation service (FRA-55).

Seed assets + ohlcv bars, then exercise ``compute_and_store_factors`` /
``persist_factor_values`` / ``read_factor_values``: persistence, idempotency
(no duplicate rows on repeat), read-back equality vs the computed frame,
``source`` as part of the primary key, NaN cells skipped (``value`` NOT NULL),
and the pure-unit registry / unknown-factor paths.

Host Postgres is used directly with surgical cleanup scoped to the ``FRA55TEST``
prefix (mirrors ``test_backtest_prices.py``).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.factor import FactorValue
from app.models.ohlcv import Ohlcv
from app.services.backtest.prices import load_prices
from app.services.backtest.types import PriceField
from app.services.factors.momentum import momentum
from app.services.factors.service import (
    FACTOR_REGISTRY,
    compute_and_store_factors,
    compute_factors,
    persist_factor_values,
    read_factor_values,
)
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

PREFIX = "FRA55TEST"
SRC = "FRA55SRC"


# ---------------------------------------------------------------------------
# DB helpers + fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    owned = "SELECT id FROM assets WHERE symbol LIKE :p"
    db.execute(text(f"DELETE FROM factor_values WHERE asset_id IN ({owned})"), {"p": f"{PREFIX}%"})
    db.execute(text(f"DELETE FROM ohlcv WHERE asset_id IN ({owned})"), {"p": f"{PREFIX}%"})
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


def _make_asset(db: Session, symbol: str) -> Asset:
    asset = Asset(
        symbol=symbol,
        name=f"Test {symbol}",
        exchange="NASDAQ",
        asset_type="stock",
        currency="USD",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _add_bar(db: Session, asset_id: uuid.UUID, day: date, price: int, source: str) -> None:
    db.add(
        Ohlcv(
            asset_id=asset_id,
            time=datetime(day.year, day.month, day.day, tzinfo=UTC),
            source=source,
            open=Decimal(price),
            high=Decimal(price),
            low=Decimal(price),
            close=Decimal(price),
            adjusted_close=Decimal(price),
            volume=1000,
        )
    )


@pytest.fixture()
def seeded_universe(db_session: Session) -> tuple[list[uuid.UUID], date, date]:
    """Seed two NASDAQ assets with ~50 business days of trending prices; return
    (asset_ids, start, end). Asset A drifts up, B drifts down → momentum
    distinguishes them."""
    a = _make_asset(db_session, f"{PREFIX}-A")
    b = _make_asset(db_session, f"{PREFIX}-B")
    days = pd.bdate_range("2023-01-02", periods=50)
    for j, day_ts in enumerate(days):
        day = day_ts.date()
        price_a = round(100 * (1.002**j))
        price_b = round(100 * (0.998**j))
        _add_bar(db_session, a.id, day, price_a, SRC)
        _add_bar(db_session, b.id, day, price_b, SRC)
    db_session.commit()
    start = days[0].date()
    end = days[-1].date()
    return [a.id, b.id], start, end


def _count(db: Session, *filters: object) -> int:
    stmt = select(func.count()).select_from(FactorValue)
    for f in filters:
        stmt = stmt.where(f)
    return int(db.scalar(stmt) or 0)


# ---------------------------------------------------------------------------
# 1) compute_and_store — persists factor values
# ---------------------------------------------------------------------------


def test_compute_and_store_persists_values(
    db_session: Session, seeded_universe: tuple[list[uuid.UUID], date, date]
) -> None:
    asset_ids, start, end = seeded_universe
    n = compute_and_store_factors(
        db_session,
        universe=asset_ids,
        source=SRC,
        start=start,
        end=end,
        price_field=PriceField.ADJUSTED,
        factor_names=["momentum_21", "rsi_14", "macd_hist"],
    )
    assert n > 0
    # 每个因子都有行。
    assert _count(db_session, FactorValue.factor_name == "momentum_21") > 0
    assert _count(db_session, FactorValue.factor_name == "rsi_14") > 0
    assert _count(db_session, FactorValue.factor_name == "macd_hist") > 0


# ---------------------------------------------------------------------------
# 2) idempotency — repeat does not add duplicate rows
# ---------------------------------------------------------------------------


def test_repeat_compute_is_idempotent(
    db_session: Session, seeded_universe: tuple[list[uuid.UUID], date, date]
) -> None:
    asset_ids, start, end = seeded_universe
    kwargs = {
        "universe": asset_ids,
        "source": SRC,
        "start": start,
        "end": end,
        "price_field": PriceField.ADJUSTED,
        "factor_names": ["momentum_21"],
    }
    n1 = compute_and_store_factors(db_session, **kwargs)
    count1 = _count(db_session, FactorValue.source == SRC, FactorValue.factor_name == "momentum_21")
    n2 = compute_and_store_factors(db_session, **kwargs)
    count2 = _count(db_session, FactorValue.source == SRC, FactorValue.factor_name == "momentum_21")
    # 幂等:行数不变、返回行数相同、无重复。
    assert count1 == count2
    assert n1 == n2
    # PK (asset_id, factor_name, time, source) 唯一 → 无重复组合。
    dupes = db_session.execute(
        select(
            FactorValue.asset_id,
            FactorValue.factor_name,
            FactorValue.time,
            FactorValue.source,
        )
        .group_by(
            FactorValue.asset_id,
            FactorValue.factor_name,
            FactorValue.time,
            FactorValue.source,
        )
        .having(func.count() > 1)
    ).all()
    assert list(dupes) == []


# ---------------------------------------------------------------------------
# 3) read-back — stored values match the computed frame
# ---------------------------------------------------------------------------


def test_read_back_matches_computed(
    db_session: Session, seeded_universe: tuple[list[uuid.UUID], date, date]
) -> None:
    asset_ids, start, end = seeded_universe
    compute_and_store_factors(
        db_session,
        universe=asset_ids,
        source=SRC,
        start=start,
        end=end,
        price_field=PriceField.ADJUSTED,
        factor_names=["momentum_21"],
    )
    prices = load_prices(db_session, asset_ids, SRC, start, end, PriceField.ADJUSTED)
    computed = momentum(prices, 21)
    read = read_factor_values(
        db_session,
        asset_ids=asset_ids,
        factor_name="momentum_21",
        source=SRC,
        start=start,
        end=end,
    )
    read.index = pd.DatetimeIndex(read.index)
    # 每列:存储值覆盖所有计算出的非 NaN 点,且数值一致(8 位小数截断内)。
    for col in computed.columns:
        comp = computed[col].dropna()
        got = read[col].dropna()
        assert len(comp) == len(got), f"row count mismatch for {col}"
        np.testing.assert_allclose(got.to_numpy(), comp.to_numpy(), rtol=1e-6)


# ---------------------------------------------------------------------------
# 4) source is part of the primary key — different sources coexist
# ---------------------------------------------------------------------------


def test_source_is_part_of_primary_key(
    db_session: Session, seeded_universe: tuple[list[uuid.UUID], date, date]
) -> None:
    asset_ids, start, end = seeded_universe
    prices = load_prices(db_session, asset_ids, SRC, start, end, PriceField.ADJUSTED)
    frames = compute_factors(prices, ["rsi_14"])
    asset_map = {col: uuid.UUID(col) for col in prices.columns}

    n_a = persist_factor_values(
        db_session, factor_frames=frames, asset_id_by_col=asset_map, source="SRC_A"
    )
    n_b = persist_factor_values(
        db_session, factor_frames=frames, asset_id_by_col=asset_map, source="SRC_B"
    )
    assert n_a == n_b > 0
    assert _count(db_session, FactorValue.source == "SRC_A") == n_a
    assert _count(db_session, FactorValue.source == "SRC_B") == n_b
    # 两 source 共存,总行数翻倍(source 在 PK 中,不冲突)。
    assert _count(db_session) == n_a + n_b


# ---------------------------------------------------------------------------
# 5) NaN cells are not stored (value NOT NULL)
# ---------------------------------------------------------------------------


def test_nan_cells_not_stored(
    db_session: Session, seeded_universe: tuple[list[uuid.UUID], date, date]
) -> None:
    asset_ids, start, end = seeded_universe
    compute_and_store_factors(
        db_session,
        universe=asset_ids,
        source=SRC,
        start=start,
        end=end,
        price_field=PriceField.ADJUSTED,
        factor_names=["momentum_21"],
    )
    prices = load_prices(db_session, asset_ids, SRC, start, end, PriceField.ADJUSTED)
    read = read_factor_values(
        db_session,
        asset_ids=asset_ids,
        factor_name="momentum_21",
        source=SRC,
        start=start,
        end=end,
    )
    read.index = pd.DatetimeIndex(read.index)
    # momentum_21 前 21 行为 NaN(窗口不足)→ 最早存储 time >= 第 22 个交易日。
    assert read.index.min() >= prices.index[21]


# ---------------------------------------------------------------------------
# 6) pure-unit — registry + unknown factor
# ---------------------------------------------------------------------------


def test_factor_registry_has_default_factors() -> None:
    # 覆盖 FRA-49(momentum/reversal)+ FRA-50(rsi/MACD/volatility)默认档。
    assert {"momentum_21", "momentum_63", "momentum_126", "reversal_5", "reversal_21"} <= set(
        FACTOR_REGISTRY
    )
    assert {"macd_hist", "rsi_14", "volatility_20d", "volatility_63d"} <= set(FACTOR_REGISTRY)


def test_compute_factors_unknown_name_raises() -> None:
    prices = pd.DataFrame({"a": [1.0, 2.0]})
    with pytest.raises(ValueError, match="unknown factor"):
        compute_factors(prices, ["bogus_factor"])
