"""Baseline portfolio strategies implementing the ``Strategy`` protocol (FRA-29).

每个策略实现 ``app.services.backtest.protocols.Strategy``(FRA-25),输出与
价格宽表同形状的目标权重,供 ``run_backtest``(FRA-28)消费。所有策略遵守
反双重滞后契约:**不**自行 ``shift``,由引擎统一负责执行延迟。
"""

from app.services.backtest.strategies.buy_hold import BuyAndHoldStrategy
from app.services.backtest.strategies.equal_weight import EqualWeightStrategy
from app.services.backtest.strategies.ma_crossover import MACrossoverStrategy
from app.services.backtest.strategies.momentum import MomentumStrategy
from app.services.backtest.strategies.reversal import ReversalStrategy

__all__ = [
    "BuyAndHoldStrategy",
    "EqualWeightStrategy",
    "MACrossoverStrategy",
    "MomentumStrategy",
    "ReversalStrategy",
]
