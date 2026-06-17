"""Equity-curve persistence helper — strategy + benchmark rows (FRA-41).

把 ``BacktestResult``(策略曲线)与可选的 ``BenchmarkComparison``(基准曲线)
映射成 ``EquityCurvePoint`` ORM 列表(strategy + benchmark 同表,以 ``series_kind``
区分),供回测触发 API 一行 ``session.add_all`` 入库。本模块**纯构造,不碰
session** —— 实际持久化与事务由回测触发 API issue 负责(同 ``to_metrics_orm``
模式)。

对齐与 NaN 语义:
    * 策略行:逐交易日写 ``equity``(= equity_curve)、``daily_return``(= net 日
      收益)、``drawdown``(= equity/cummax − 1);引擎产出无 NaN,全部有效。
    * 基准行:``benchmark_equity`` 前缀段(基准从未覆盖策略窗口)为 NaN → 跳过
      (equity NOT NULL 不接受 NaN);有效段写 equity、``daily_return``(=
      pct_change)、``drawdown``(= ``comparison.benchmark_drawdown``)。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import pandas as pd

from app.models.backtest import SERIES_KINDS, EquityCurvePoint
from app.services.backtest.benchmark import BenchmarkComparison
from app.services.backtest.types import BacktestResult


def build_equity_curve_points(
    run_id: uuid.UUID,
    result: BacktestResult,
    comparison: BenchmarkComparison | None = None,
) -> list[EquityCurvePoint]:
    """构造策略(+ 可选 benchmark)权益曲线 ORM 点(纯构造,不碰 session)。

    Args:
        run_id: 所属 ``BacktestRun`` 的 UUID(由 API 创建 run 后传入)。
        result: 已完成的回测结果;逐日写 strategy 行(equity=equity_curve、
            daily_return=daily_returns(net)、drawdown=equity/cummax−1)。
        comparison: 可选 benchmark 对比(FRA-33);提供则追加 benchmark 行。其
            ``benchmark_equity`` 的前缀 NaN 段(基准从未覆盖)被跳过。

    Returns:
        ``EquityCurvePoint`` 列表;``series_kind='strategy'`` 全部交易日 +(若给
        comparison)``series_kind='benchmark'`` 的有效交易日。未持久化 —— 由调用方
        ``add_all`` + commit。
    """
    points: list[EquityCurvePoint] = []

    # ---- strategy 行:equity / net daily_return / drawdown ----
    equity = result.equity_curve
    drawdown = equity / equity.cummax() - 1.0
    for ts in equity.index:
        points.append(
            EquityCurvePoint(
                backtest_run_id=run_id,
                series_kind=SERIES_KINDS[0],  # "strategy"
                time=_to_dt(ts),
                equity=_to_dec(equity.loc[ts]),
                daily_return=_to_dec(result.daily_returns.loc[ts]),
                drawdown=_to_dec(drawdown.loc[ts]),
            )
        )

    # ---- benchmark 行(可选):跳过前缀 NaN 段(equity NOT NULL)----
    if comparison is not None:
        bench_equity = comparison.benchmark_equity
        bench_ret = bench_equity.pct_change().fillna(0.0)
        bench_dd = comparison.benchmark_drawdown
        for ts in bench_equity.dropna().index:
            points.append(
                EquityCurvePoint(
                    backtest_run_id=run_id,
                    series_kind=SERIES_KINDS[1],  # "benchmark"
                    time=_to_dt(ts),
                    equity=_to_dec(bench_equity.loc[ts]),
                    daily_return=_to_dec(bench_ret.loc[ts]),
                    drawdown=_to_dec(bench_dd.loc[ts]),
                )
            )

    return points


def _to_dec(value: object) -> Decimal | None:
    """数值 → Decimal(可入库);None / NaN / 非数值 → None(Numeric 不接受 NaN)。"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, (int, float)):
        f = float(value)
        return None if pd.isna(f) else Decimal(str(f))
    return None


def _to_dt(ts: pd.Timestamp) -> datetime:
    """tz-aware UTC Timestamp → tz-aware datetime(匹配 ``time`` 列)。"""
    py_dt: datetime = ts.to_pydatetime()
    return py_dt
