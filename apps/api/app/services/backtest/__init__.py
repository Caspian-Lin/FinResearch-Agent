"""Backtesting engine — strategy/engine protocols and data contracts (FRA-25).

Week 2 foundation. This package currently exposes only the typed interfaces;
the engine ``run`` loop, strategy weight math, and risk metrics are added by
later issues. See ``docs/backtesting-methodology.md`` §接口契约.
"""

from app.services.backtest.protocols import BacktestEngine, Strategy
from app.services.backtest.types import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    PriceField,
    RebalanceFreq,
    Trade,
)

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestMetrics",
    "BacktestResult",
    "PriceField",
    "RebalanceFreq",
    "Strategy",
    "Trade",
]
