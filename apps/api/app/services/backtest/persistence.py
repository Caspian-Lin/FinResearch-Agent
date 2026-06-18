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

import logging
import uuid
from datetime import datetime
from decimal import Decimal

import pandas as pd

from app.models.backtest import SERIES_KINDS, EquityCurvePoint
from app.models.backtest import Trade as TradeORM
from app.services.backtest.benchmark import BenchmarkComparison
from app.services.backtest.types import BacktestConfig, BacktestResult

logger = logging.getLogger(__name__)


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


def build_trade_points(
    run_id: uuid.UUID,
    result: BacktestResult,
    prices: pd.DataFrame,
    config: BacktestConfig,
) -> list[TradeORM]:
    """把 FRA-28 engine 的 weight-delta ``Trade`` 转成 ORM ``Trade``(quantity/price/cost/side)。

    engine 的 ``Trade`` 记的是**权重变动**(weight_before / after / turnover),不含价格 /
    股数;ORM ``Trade`` 要 quantity(股)/ price / cost(货币)/ side。逐笔用当日该资产价格
    + 当日组合净值(``equity_curve[t]``)把权重变动定量化:

    * ``price``        = ``prices[t, asset]``(当日成交价)
    * ``value_traded`` = ``(weight_after − weight_before) × equity_curve[t]``(价值变动)
    * ``quantity``     = ``|value_traded / price|``(股数,绝对值;``side`` 区分方向)
    * ``side``         = ``buy`` if ``weight_delta > 0`` else ``sell``
    * ``cost``         = ``|value_traded| × cost_bps / 1e4``(单边成本,货币)

    price NaN(停牌 / 数据缺失,无法定价)的 trade 跳过 + warning —— 不丢失其它 trade,
    也不让单笔定价失败拖垮整个 run。

    Args:
        run_id: 所属 ``BacktestRun`` UUID。
        result: engine 产出(含 ``trades`` + ``equity_curve``)。
        prices: 与 engine 同源的价格宽表(index=UTC 午夜,columns=``str(asset_id)``)。
        config: 取 ``cost_bps`` 算单边成本。

    Returns:
        ORM ``Trade`` 列表(纯构造,不碰 session);price NaN 的 trade 被跳过。
    """
    cost_rate = config.cost_bps / 1e4
    equity = result.equity_curve
    points: list[TradeORM] = []
    skipped = 0
    for trade in result.trades:
        if trade.asset_id not in prices.columns:
            skipped += 1
            continue
        price = prices.loc[trade.date, trade.asset_id]
        if price is None or pd.isna(price) or float(price) <= 0.0:
            skipped += 1
            continue
        price_f = float(price)
        portfolio_value = float(equity.loc[trade.date])
        weight_delta = trade.weight_after - trade.weight_before
        value_traded = weight_delta * portfolio_value
        quantity = abs(value_traded / price_f)
        cost = abs(value_traded) * cost_rate
        points.append(
            TradeORM(
                backtest_run_id=run_id,
                time=_to_dt(trade.date),
                asset_id=uuid.UUID(trade.asset_id),
                side="buy" if weight_delta > 0 else "sell",
                quantity=_to_dec(quantity) or Decimal("0"),
                price=_to_dec(price_f) or Decimal("0"),
                cost=_to_dec(cost) or Decimal("0"),
            )
        )
    if skipped:
        logger.warning(
            "build_trade_points run_id=%s skipped %d/%d trade(s) with missing/non-positive price",
            run_id,
            skipped,
            len(result.trades),
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
