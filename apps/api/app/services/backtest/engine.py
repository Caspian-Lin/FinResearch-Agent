"""Vectorized backtest engine core — target weights → equity/returns/turnover (FRA-28).

``run_backtest`` is a pure function: it turns any ``Strategy``'s *decision-day*
target weights into a full ``BacktestResult`` (equity, daily returns, turnover,
positions, trades). It is vectorized over the trading-day index and enforces a
single anti-look-ahead boundary so that strategy and engine never double-shift.

防前视 / 反双重滞后契约
-------------------------
策略只产出"决策日目标权重"(每个交易日一行,与 ``prices`` 同形状),**不
自己 ``shift``**。引擎统一负责执行延迟::

    target  = strategy.weights(prices)                 # 决策日权重(同形状)
    decision = rebalance 日采样 target 后 forward-fill  # 每日的"最近一次决策"
    holdings = decision.shift(1).fillna(0)             # t 日持仓由 t-1 及更早决策决定
    gross    = (holdings * asset_returns).sum(axis=1)

因此 t 日的目标权重**只在 t+1 日及之后**影响收益——t 日信号不影响 t 日
收益,且策略层无需(也不应)再 shift 一次。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.backtest.protocols import Strategy
from app.services.backtest.types import (
    REBALANCE_FREQ_OFFSET,
    BacktestConfig,
    BacktestResult,
    RebalanceFreq,
    Trade,
)


def run_backtest(
    prices: pd.DataFrame,
    strategy: Strategy,
    config: BacktestConfig,
) -> BacktestResult:
    """把策略目标权重跑成回测结果(向量化、防前视)。

    Parameters
    ----------
    prices:
        FRA-25/FRA-27 宽表约定:index = tz-aware UTC midnight 交易日,
        columns = ``str(asset_id)``,values = ``float`` 价格(无 forward-fill)。
    strategy:
        任何满足 :class:`~app.services.backtest.protocols.Strategy` 协议的对象。
        其 ``weights(prices)`` 返回与 ``prices`` 同形状的**决策日**目标权重
        (行权和 ∈ [0, 1]),策略**不应**自行 ``shift``。
    config:
        本次运行的不可变参数;``rebalance`` 决定换仓频率,``cost_bps`` 决定单
        边交易成本(bps),``initial_capital`` 为初始资金。

    Returns
    -------
    BacktestResult
        net 口径:``equity_curve`` / ``daily_returns`` 为扣除成本后的序列;
        ``turnover`` 为每日换手(单边 |Δw| 之和);``positions`` 为每日持仓权重;
        ``trades`` 为每个换仓日逐资产的权重变动记录;``metrics`` 恒为
        ``None``(由 risk-metrics issue 填充)。

    Raises
    ------
    ValueError
        universe 为空(prices 无列或无行)时。
    """
    # ------------------------------------------------------------------ guard
    if prices.shape[1] == 0 or prices.shape[0] == 0:
        raise ValueError(
            f"prices must contain at least one asset and one row (got shape={prices.shape})"
        )

    # ----------------------------------------------------- 1) 决策日目标权重
    # 策略返回"决策日"权重(同形状);本引擎统一负责 shift,策略无需 shift。
    target = strategy.weights(prices)
    target = _align_to_prices(target, prices)
    # 全 NaN 列资产:该资产无可执行权重 → 视作 0(与无持仓等价),保留列便于对齐。
    target = target.fillna(0.0)

    # --------------------------------------------- 2) rebalance 采样 + ffill
    decision = _sample_rebalance(target, config.rebalance)

    # ------------------------------------------------------ 3) 防前视持仓
    # t 日持仓由 t-1(及更早)的最近一次 rebalance 决策决定 → shift(1)。
    # 首行 NaN → fillna(0):首日全现金、无收益,从 t=1 起持有 t-1 决策。
    holdings = decision.shift(1).fillna(0.0)

    # ---------------------------------------------------------- 4) 资产收益
    asset_returns = prices.pct_change()

    # ------------------------------------------------------------ 5) gross
    gross = (holdings * asset_returns).sum(axis=1)
    # 首行收益固定为 0(首日建仓,无持仓收益)。
    gross.iloc[0] = 0.0

    # --------------------------------------------------------- 6) turnover
    # 单边换手 = |Δholdings|.sum(axis=1)。holdings 首行恒为 0(全现金),其前
    # 一行(虚拟)亦为 0 → 首日 turnover=0;真正的"建仓"发生在 t1(0→首组
    # 决策),由 diff 自然捕获。
    turnover = (holdings - holdings.shift(1).fillna(0.0)).abs().sum(axis=1)

    # ----------------------------------------------------------- 7) net
    cost_rate = config.cost_bps / 1e4
    net = gross - turnover * cost_rate
    # cost_bps=0 时 net == gross(浮点一致);首行亦为 0。
    net.iloc[0] = 0.0

    # ---------------------------------------------------- 8) equity curve
    equity_curve = (1.0 + net).cumprod() * config.initial_capital
    # 首日精确等于 initial_capital(cumprod 首项为 1)。
    equity_curve.iloc[0] = config.initial_capital

    # --------------------------------------------------------- 9) trades
    trades = _build_trades(holdings)

    return BacktestResult(
        config=config,
        equity_curve=equity_curve,
        daily_returns=net,
        turnover=turnover,
        positions=holdings,
        trades=trades,
        metrics=None,
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _align_to_prices(target: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """对齐策略输出到 prices 的 index/columns,缺列补 0、缺行沿用前值。

    策略可能返回列顺序不同或缺列(例如剔除全 NaN 资产);统一 reindex 到
    prices 的形状,缺列按 0 权重处理,缺行(罕见)用前值填充,剩余 NaN 补 0。
    """
    aligned = target.reindex(index=prices.index, columns=prices.columns).ffill()
    return aligned.fillna(0.0)


def _sample_rebalance(target: pd.DataFrame, freq: RebalanceFreq) -> pd.DataFrame:
    """按 ``freq`` 采样目标权重并 forward-fill 到每个交易日。

    * DAILY:每个交易日都是 rebalance 日 → 直接返回 target。
    * WEEKLY:每周最后一个交易日为 rebalance 日(``W-FRI``)。
    * MONTHLY:每月最后一个交易日为 rebalance 日(``ME``)。

    rebalance 日之间的非 rebalance 日沿用上一组决策(forward-fill),模拟
    "持有期内不换仓"。rebalance 日之前尚无决策的初始段保持 NaN(随后由调用方
    ``shift(1).fillna(0)`` 变为全现金)。

    实现细节:用 ``pd.Grouper(freq=offset)`` 把交易日 index 分组,取每组最后
    一行的位置作为 rebalance 日;非 rebalance 日的权重置 NaN,再 ffill。
    """
    if freq is RebalanceFreq.DAILY:
        return target.copy()

    offset = REBALANCE_FREQ_OFFSET[freq]
    idx = target.index

    # 每组(周/月)的最后一个交易日位置即 rebalance 日。
    groups = pd.Series(np.arange(len(idx)), index=idx).groupby(pd.Grouper(freq=offset))
    rebalance_positions = groups.last().to_numpy()  # 每组最后一行的行号
    mask = np.zeros(len(idx), dtype=bool)
    mask[rebalance_positions] = True

    decision = target.copy()
    # 非 rebalance 日整行置 NaN,再 forward-fill。
    decision[~mask] = np.nan
    return decision.ffill()


def _build_trades(holdings: pd.DataFrame) -> list[Trade]:
    """逐换仓日、逐资产构造 :class:`Trade` 记录。

    ``holdings = decision.shift(1).fillna(0)`` 是实际持仓。一次换仓 = holdings
    在某日相对前一日发生权重变动;对每个有变动的 (date, asset) 产一个 Trade:

    * ``date``         :换仓生效日(holdings 发生变动的那一行)
    * ``weight_before``:换仓前持仓权重(holdings 前一行)
    * ``weight_after`` :换仓后持仓权重(holdings 当前行)
    * ``turnover``     :|weight_after - weight_before|

    首日建仓(weight_before 视作 0)也算一次换仓;持有期(diff=0)无 trade。
    """
    trades: list[Trade] = []
    asset_ids = [str(c) for c in holdings.columns]

    values = holdings.to_numpy(dtype=float)
    prev = np.zeros(values.shape[1])  # 首日建仓前视作全 0
    for i, ts in enumerate(holdings.index):
        curr = values[i]
        deltas = np.abs(curr - prev)
        for j, asset_id in enumerate(asset_ids):
            if deltas[j] == 0.0 or np.isnan(deltas[j]):
                continue
            before = float(prev[j]) if not np.isnan(prev[j]) else 0.0
            after = float(curr[j]) if not np.isnan(curr[j]) else 0.0
            trades.append(
                Trade(
                    date=ts,
                    asset_id=asset_id,
                    weight_before=before,
                    weight_after=after,
                    turnover=abs(after - before),
                )
            )
        prev = curr
    return trades
