"""Backtesting engine — interfaces, data contracts, and price reader.

Week 2 foundation: typed interfaces (FRA-25) plus the price-series reader
(FRA-27). The engine ``run`` loop, strategy weight math, and risk metrics are
added by later issues. See ``docs/backtesting-methodology.md`` §接口契约.
"""

from app.services.backtest.benchmark import (
    BenchmarkComparison,
    compute_benchmark_comparison,
    load_benchmark_prices,
)
from app.services.backtest.engine import run_backtest
from app.services.backtest.metrics import (
    compute_result_metrics,
    compute_risk_metrics,
    to_metrics_orm,
)
from app.services.backtest.persistence import build_equity_curve_points
from app.services.backtest.prices import load_prices
from app.services.backtest.protocols import BacktestEngine, Strategy
from app.services.backtest.strategies import (
    BuyAndHoldStrategy,
    EqualWeightStrategy,
    MACrossoverStrategy,
    MomentumStrategy,
    ReversalStrategy,
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
    "BenchmarkComparison",
    "BuyAndHoldStrategy",
    "EqualWeightStrategy",
    "MACrossoverStrategy",
    "MomentumStrategy",
    "PriceField",
    "RebalanceFreq",
    "ReversalStrategy",
    "Strategy",
    "Trade",
    "build_equity_curve_points",
    "compute_benchmark_comparison",
    "compute_result_metrics",
    "compute_risk_metrics",
    "load_benchmark_prices",
    "load_prices",
    "run_backtest",
    "to_metrics_orm",
]
