"""Backtesting engine — interfaces, data contracts, and price reader.

Week 2 foundation: typed interfaces (FRA-25) plus the price-series reader
(FRA-27). The engine ``run`` loop, strategy weight math, and risk metrics are
added by later issues. See ``docs/backtesting-methodology.md`` §接口契约.
"""

from app.services.backtest.engine import run_backtest
from app.services.backtest.prices import load_prices
from app.services.backtest.protocols import BacktestEngine, Strategy
from app.services.backtest.strategies import (
    BuyAndHoldStrategy,
    EqualWeightStrategy,
    MACrossoverStrategy,
)
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
    "BuyAndHoldStrategy",
    "EqualWeightStrategy",
    "MACrossoverStrategy",
    "PriceField",
    "RebalanceFreq",
    "Strategy",
    "Trade",
    "load_prices",
    "run_backtest",
]
