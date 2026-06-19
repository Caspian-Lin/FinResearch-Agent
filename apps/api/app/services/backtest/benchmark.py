"""Benchmark 对比服务 —— 策略 vs QQQ/SPY 等基准(FRA-33)。

本模块**只产数据**,不计算 Sharpe/Beta 等统计量,也不画前端图。给定一条已完成的
策略回测结果(``BacktestResult``)与基准价格宽表,产出对齐到策略交易日
(``result.equity_curve.index``)的可比 equity / drawdown / 超额收益序列。

防前视契约:
    benchmark equity 用基准**已实现收盘价**的累积收益 ``(1+ret).cumprod() * initial``,
    其中 ``ret = price.pct_change().fillna(0.0)`` 仅依赖截至当日的价格(无 shift、无未来
    价格)。基准作为 buy & hold 参照,与策略 ``net`` 口径(扣成本后)对比,二者均为
    "截至 t 日已实现"的同期净值,口径一致、无未来信息泄露。

对齐与缺数据处理(逐条语义见 ``compute_benchmark_comparison`` docstring)。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from app.services.backtest.prices import load_prices
from app.services.backtest.types import BacktestResult, PriceField


@dataclass(slots=True)
class BenchmarkComparison:
    """策略与单一基准(buy & hold)对齐后的可比序列(FRA-33)。

    所有序列均 reindex 到策略交易日 ``result.equity_curve.index``;基准缺失的交易日
    用最近已知值延续(``ffill``),基准从未覆盖的前缀段保持 ``NaN``(详见
    ``compute_benchmark_comparison``)。

    Attributes:
        strategy_equity: 策略净值(= ``result.equity_curve``,原样回填,便于统一视图)。
        benchmark_equity: 基准 buy & hold 净值,首日精确等于 ``initial_capital``;
            前缀(基准从未上市)段为 ``NaN``。
        strategy_drawdown: 策略回撤 ``equity / equity.cummax() - 1.0``,恒 ≤ 0。
        benchmark_drawdown: 基准回撤,同口径;前缀 NaN 段保持 NaN。
        excess_returns: 逐日超额 = ``strategy_daily_returns - benchmark_daily_returns``;
            基准前缀 NaN 段为 NaN。

    Note:
        ``config`` 引用可选(便于上层序列化/日志);不参与对比计算本身。
    """

    strategy_equity: pd.Series
    benchmark_equity: pd.Series
    strategy_drawdown: pd.Series
    benchmark_drawdown: pd.Series
    excess_returns: pd.Series
    config: BacktestResult | None = None


def compute_benchmark_comparison(
    result: BacktestResult,
    benchmark_prices: pd.DataFrame,
) -> BenchmarkComparison:
    """计算策略与单一基准的对齐 equity / drawdown / 超额收益(纯计算,不碰 DB)。

    Args:
        result: 已完成的策略回测结果;以其 ``equity_curve.index`` 为对齐基准。
        benchmark_prices: 单资产宽表,columns 含 benchmark asset_id(取第一列即可)。
            index 为 tz-aware UTC 午夜交易日、值为 float 收盘价(无 forward-fill,
            遵循 ``load_prices`` 约定)。

    Returns:
        对齐到策略交易日的 ``BenchmarkComparison``。

    Raises:
        ValueError: 基准价格表为空、或不包含任何有效价格(全 ``NaN``)。
        ValueError: 基准**完全不覆盖**策略交易日区间(reindex + ffill 后仍无任何
            有效点),此时无基准可对照。

    对齐与缺数据处理语义(逐条):

    1. **基准日收益** ``ret = price.pct_change().fillna(0.0)``:首日无前值 →
       ``pct_change`` 产 ``NaN`` → ``fillna(0.0)`` 置 0,确保 cumprod 首项为 1、
       equity 首日 = initial_capital。
    2. **基准 equity** = ``(1 + ret).cumprod() * result.config.initial_capital``,
       首日精确等于 initial_capital。
    3. **reindex 到策略交易日** ``result.equity_curve.index``:策略交易日 ⊃ 基准
       交易日时,缺失点先为 ``NaN``。
    4. **ffill 缺失日**:reindex 后对基准 equity / 基准日收益做 ``ffill()`` —— 模拟
       "基准该交易日无新价则沿用前值";这符合 buy & hold 口径(无新行情 = 净值不动)。
    5. **前缀 NaN 段不补**:策略 index 头部若基准从未有过数据(无前值可 ffill),
       这些点保持 ``NaN`` —— 该段策略也无基准对照,equity/drawdown/excess 对应位
       均为 NaN(允许,但需至少有一个有效点)。
    6. **至少一个有效点**:reindex + ffill 后若基准 equity 全 ``NaN``(基准完全不
       覆盖策略区间)→ ``raise ValueError``。
    7. **drawdown** = ``equity / equity.cummax() - 1.0``:对策略与基准各算一条;
       基准前缀 NaN 段(无前值)的 cummax 仍为 NaN → drawdown 保持 NaN。
    8. **excess_returns** = ``result.daily_returns - benchmark_daily_returns``:
       逐日相减,对齐策略 index;基准前缀 NaN 段 excess 为 NaN。
    """
    if benchmark_prices.empty:
        raise ValueError("benchmark price frame is empty — no benchmark to compare against")
    if benchmark_prices.shape[1] == 0:
        raise ValueError("benchmark price frame has no columns — no benchmark to compare against")

    # 取基准价格序列(宽表单列):首列即基准资产。
    bench_price = benchmark_prices.iloc[:, 0]

    # 基准日收益:首日 pct_change 为 NaN → 0,保证 cumprod 首项 = 1。
    bench_returns = bench_price.pct_change().fillna(0.0)

    # 基准 buy & hold 净值(口径与策略 net 对齐:截至当日的已实现净值,无未来信息)。
    initial = result.config.initial_capital
    bench_equity = (1.0 + bench_returns).cumprod() * initial
    # cumprod 首项为 1 → equity 首日 = initial_capital(浮点守恒)。
    bench_equity.iloc[0] = initial

    # ---- 对齐到策略交易日 -------------------------------------------------
    strat_index = result.equity_curve.index

    # reindex 到策略 index(基准未覆盖的策略交易日 → NaN),再 ffill:基准缺失日
    # 沿用最近已知值(无新行情则净值不动,buy & hold 口径)。
    bench_equity_aligned = bench_equity.reindex(strat_index).ffill()
    bench_returns_aligned = bench_returns.reindex(strat_index).ffill()

    # reindex + ffill 后仍全 NaN → 基准完全不覆盖策略区间,无可对照。
    if bench_equity_aligned.isna().all():
        raise ValueError(
            "benchmark has no price data overlapping the strategy trading days "
            f"[{strat_index.min()}, {strat_index.max()}] — cannot align"
        )

    # ---- drawdown(策略 / 基准各一条)------------------------------------
    strategy_equity = result.equity_curve
    strategy_drawdown = strategy_equity / strategy_equity.cummax() - 1.0
    # 基准前缀 NaN 段:cummax 为 NaN → drawdown 保持 NaN(不强行补 0)。
    benchmark_drawdown = bench_equity_aligned / bench_equity_aligned.cummax() - 1.0

    # ---- 超额收益(逐日)--------------------------------------------------
    excess_returns = result.daily_returns - bench_returns_aligned

    return BenchmarkComparison(
        strategy_equity=strategy_equity,
        benchmark_equity=bench_equity_aligned,
        strategy_drawdown=strategy_drawdown,
        benchmark_drawdown=benchmark_drawdown,
        excess_returns=excess_returns,
        config=result,
    )


def load_benchmark_prices(
    db: Session,
    benchmark_asset_id: uuid.UUID,
    start: date,
    end: date,
    price_field: PriceField,
    source: str = "yfinance",
) -> pd.DataFrame:
    """加载单一基准资产的收盘价宽表(经 ``load_prices``,无 forward-fill)。

    薄封装于 ``load_prices`` 之上:把基准视为单资产 universe 取回宽表
    (index = tz-aware UTC 午夜交易日,columns = ``str(benchmark_asset_id)``)。
    缺数据(空 DataFrame)→ ``raise ValueError``,避免上层拿到空表后静默产出全 NaN
    对比。

    Args:
        db: SQLAlchemy 会话(复用 ``load_prices`` 的 ORM 读路径)。
        benchmark_asset_id: 基准资产 UUID(如 QQQ / SPY)。
        start: 窗口起点(含)。
        end: 窗口终点(含)。
        price_field: 价格字段(收盘 / 复权收盘)。
        source: ohlcv 数据源,默认 ``"yfinance"``(与 FRA-8 适配器一致)。

    Returns:
        单列宽表,columns 含 ``str(benchmark_asset_id)``。

    Raises:
        ValueError: ``load_prices`` 返回空(基准在该窗口无任何价格)。
    """
    wide = load_prices(
        db=db,
        universe=(benchmark_asset_id,),
        source=source,
        start=start,
        end=end,
        price_field=price_field,
    )
    if wide.empty:
        raise ValueError(
            f"benchmark asset {benchmark_asset_id} has no price data in "
            f"[{start}, {end}] (source={source!r}, field={price_field.value})"
        )
    return wide
