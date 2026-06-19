"""Persist backtest trades — weight-delta → quantity/price/cost conversion (FRA-42).

纯单元(无 DB):``build_trade_points`` 把 engine 的 weight-delta ``Trade`` 转成 ORM
``Trade``(quantity/price/cost/side),price NaN / 缺列 跳过,cost_bps=0 → cost=0,
空 trades → 空。DB 集成见 ``test_backtest_execution.py::test_execute_persists_trades``。
"""

from __future__ import annotations

import uuid
from datetime import date

import numpy as np
import pandas as pd
import pytest
from app.services.backtest.persistence import build_trade_points
from app.services.backtest.types import BacktestConfig, BacktestResult, Trade


def _config(cost_bps: float = 0.0) -> BacktestConfig:
    return BacktestConfig(
        universe=("A", "B"),
        start=date(2024, 1, 2),
        end=date(2024, 1, 4),
        strategy_name="stub",
        cost_bps=cost_bps,
    )


def _result(
    trades: list[Trade], equity_values: list[float], config: BacktestConfig
) -> BacktestResult:
    idx = pd.date_range("2024-01-02", periods=len(equity_values), freq="D", tz="UTC")
    equity = pd.Series(equity_values, index=idx, dtype="float64")
    returns = equity.pct_change().fillna(0.0)
    return BacktestResult(
        config=config,
        equity_curve=equity,
        daily_returns=returns,
        turnover=pd.Series(0.0, index=idx),
        positions=pd.DataFrame(0.0, index=idx, columns=["A"]),
        gross_returns=returns,
        trades=trades,
    )


def test_build_trade_points_converts_weight_delta_to_quantity_and_side() -> None:
    idx = pd.date_range("2024-01-02", periods=3, freq="D", tz="UTC")
    a = str(uuid.uuid4())
    prices = pd.DataFrame({a: [100.0, 100.0, 102.0]}, index=idx)
    trades = [
        Trade(date=idx[1], asset_id=a, weight_before=0.0, weight_after=1.0, turnover=1.0),
        Trade(date=idx[2], asset_id=a, weight_before=1.0, weight_after=0.5, turnover=0.5),
    ]
    config = _config(cost_bps=10.0)
    result = _result(trades, [100_000.0, 101_000.0, 100_500.0], config)

    points = build_trade_points(uuid.uuid4(), result, prices, config)

    assert len(points) == 2
    # trade1: 0→1.0 建仓 @ idx[1];value=1.0×101000=101000;qty=101000/100;cost=101000×0.001。
    assert points[0].side == "buy"
    assert points[0].asset_id == uuid.UUID(a)
    assert float(points[0].price) == pytest.approx(100.0)
    assert float(points[0].quantity) == pytest.approx(1010.0, rel=1e-6)
    assert float(points[0].cost) == pytest.approx(101.0, rel=1e-6)
    # trade2: 1.0→0.5 减仓 @ idx[2];value=−0.5×100500=−50250;qty=50250/102;cost=50250×0.001。
    assert points[1].side == "sell"
    assert float(points[1].price) == pytest.approx(102.0)
    assert float(points[1].quantity) == pytest.approx(50250.0 / 102.0, rel=1e-6)
    assert float(points[1].cost) == pytest.approx(50.25, rel=1e-6)


def test_build_trade_points_skips_nan_price_and_missing_column() -> None:
    idx = pd.date_range("2024-01-02", periods=3, freq="D", tz="UTC")
    a = str(uuid.uuid4())
    b = str(uuid.uuid4())
    prices = pd.DataFrame(
        {a: [100.0, 100.0, 102.0], b: [50.0, 50.0, np.nan]},
        index=idx,
    )
    trades = [
        Trade(date=idx[1], asset_id=a, weight_before=0.0, weight_after=1.0, turnover=1.0),  # OK
        Trade(
            date=idx[2], asset_id=b, weight_before=0.0, weight_after=1.0, turnover=1.0
        ),  # NaN price → skip
        Trade(  # asset 不在 prices 列 → skip
            date=idx[1],
            asset_id=str(uuid.uuid4()),
            weight_before=0.0,
            weight_after=1.0,
            turnover=1.0,
        ),
    ]
    config = _config()
    result = _result(trades, [100_000.0, 101_000.0, 100_500.0], config)

    points = build_trade_points(uuid.uuid4(), result, prices, config)

    assert len(points) == 1  # 只留下 a 的那笔
    assert points[0].asset_id == uuid.UUID(a)


def test_build_trade_points_cost_zero_when_cost_bps_zero() -> None:
    idx = pd.date_range("2024-01-02", periods=2, freq="D", tz="UTC")
    a = str(uuid.uuid4())
    prices = pd.DataFrame({a: [100.0, 100.0]}, index=idx)
    trades = [Trade(date=idx[1], asset_id=a, weight_before=0.0, weight_after=1.0, turnover=1.0)]
    config = _config(cost_bps=0.0)
    result = _result(trades, [100_000.0, 100_000.0], config)

    points = build_trade_points(uuid.uuid4(), result, prices, config)

    assert len(points) == 1
    assert float(points[0].cost) == pytest.approx(0.0)


def test_build_trade_points_empty_trades_returns_empty() -> None:
    idx = pd.date_range("2024-01-02", periods=2, freq="D", tz="UTC")
    a = str(uuid.uuid4())
    prices = pd.DataFrame({a: [100.0, 100.0]}, index=idx)
    config = _config()
    result = _result([], [100_000.0, 100_000.0], config)

    assert build_trade_points(uuid.uuid4(), result, prices, config) == []
