"""Equity-curve persistence helper unit tests (FRA-41) — 纯单元,无 DB。

验证 ``build_equity_curve_points`` 把 ``BacktestResult``(+ 可选
``BenchmarkComparison``)映射成 ``EquityCurvePoint`` 列表:strategy 行全交易日 +
benchmark 行有效段(跳过前缀 NaN),series_kind / equity / drawdown 正确。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pandas as pd
from app.models.backtest import SERIES_KINDS
from app.services.backtest.benchmark import BenchmarkComparison
from app.services.backtest.persistence import build_equity_curve_points
from app.services.backtest.types import BacktestConfig, BacktestResult


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-02", periods=n, freq="D", tz="UTC")


def _result(n: int = 4) -> BacktestResult:
    """单调上涨 0.01/日的回测结果(equity/daily/turnover/positions/gross 齐备)。"""
    idx = _idx(n)
    daily = pd.Series([0.0] + [0.01] * (n - 1), index=idx, name="net")
    equity = (1.0 + daily).cumprod() * 100_000.0
    return BacktestResult(
        config=BacktestConfig(
            universe=("A",),
            start=idx[0].date(),
            end=idx[-1].date(),
            strategy_name="stub",
            initial_capital=100_000.0,
        ),
        equity_curve=equity,
        daily_returns=daily,
        turnover=pd.Series(0.0, index=idx),
        positions=pd.DataFrame(0.0, index=idx, columns=["A"]),
        gross_returns=daily,
    )


def _dec(x: float) -> Decimal:
    """复刻 ``_to_dec`` 的有限值路径,供对照。"""
    return Decimal(str(float(x)))


def test_strategy_only_points_match_equity_curve() -> None:
    result = _result(4)
    points = build_equity_curve_points(uuid.uuid4(), result, comparison=None)
    # 只 strategy 行;每交易日一点。
    assert len(points) == 4
    assert all(p.series_kind == SERIES_KINDS[0] for p in points)  # "strategy"
    # equity / daily_return / drawdown 与 result 对照(同公式重算)。
    expected_dd = result.equity_curve / result.equity_curve.cummax() - 1.0
    for i, p in enumerate(points):
        assert p.equity == _dec(result.equity_curve.iloc[i])
        assert p.daily_return == _dec(result.daily_returns.iloc[i])
        assert p.drawdown == _dec(float(expected_dd.iloc[i]))
    # 首日精确 100k;首日 daily_return 0(建仓)。
    assert points[0].equity == Decimal("100000")
    assert points[0].daily_return == Decimal("0")


def test_strategy_points_carry_run_id_and_tz_aware_time() -> None:
    result = _result(2)
    run_id = uuid.uuid4()
    points = build_equity_curve_points(run_id, result)
    assert all(p.backtest_run_id == run_id for p in points)
    assert points[0].time.tzinfo is not None  # tz-aware(UTC),匹配 time 列


def test_benchmark_points_appended_with_correct_kind() -> None:
    result = _result(4)
    idx = result.equity_curve.index
    bench_equity = pd.Series(
        [100_000.0, 101_000.0, 102_000.0, 103_000.0], index=idx, name="bench"
    ).astype("float64")
    cmp = BenchmarkComparison(
        strategy_equity=result.equity_curve,
        benchmark_equity=bench_equity,
        strategy_drawdown=result.equity_curve / result.equity_curve.cummax() - 1.0,
        benchmark_drawdown=bench_equity / bench_equity.cummax() - 1.0,
        excess_returns=result.daily_returns - bench_equity.pct_change().fillna(0.0),
    )
    points = build_equity_curve_points(uuid.uuid4(), result, comparison=cmp)
    # 4 strategy + 4 benchmark。
    kinds = [p.series_kind for p in points]
    assert kinds.count(SERIES_KINDS[0]) == 4
    assert kinds.count(SERIES_KINDS[1]) == 4
    bench = [p for p in points if p.series_kind == SERIES_KINDS[1]]
    assert bench[0].equity == Decimal("100000")
    # benchmark daily_return 首日 0(pct_change().fillna(0))。
    assert bench[0].daily_return == Decimal("0")


def test_benchmark_prefix_nan_segment_skipped() -> None:
    """benchmark_equity 前缀 NaN 段(基准从未覆盖)跳过 —— equity NOT NULL。"""
    result = _result(4)
    idx = result.equity_curve.index
    bench_equity = pd.Series(
        [float("nan"), float("nan"), 100_000.0, 101_000.0], index=idx, name="bench"
    )
    cmp = BenchmarkComparison(
        strategy_equity=result.equity_curve,
        benchmark_equity=bench_equity,
        strategy_drawdown=result.equity_curve / result.equity_curve.cummax() - 1.0,
        benchmark_drawdown=bench_equity / bench_equity.cummax() - 1.0,
        excess_returns=result.daily_returns,
    )
    points = build_equity_curve_points(uuid.uuid4(), result, comparison=cmp)
    bench = [p for p in points if p.series_kind == SERIES_KINDS[1]]
    # 只 2 个有效 benchmark 点(前缀 NaN 跳过)。
    assert len(bench) == 2
    assert bench[0].equity == Decimal("100000")
