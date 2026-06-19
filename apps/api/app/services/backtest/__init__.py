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
from app.services.backtest.execution import execute_backtest_run
from app.services.backtest.metrics import (
    compute_result_metrics,
    compute_risk_metrics,
    to_metrics_orm,
)
from app.services.backtest.persistence import build_equity_curve_points, build_trade_points
from app.services.backtest.prices import load_prices
from app.services.backtest.protocols import BacktestEngine, Strategy
from app.services.backtest.sensitivity import (
    ParamImpact,
    SweepPoint,
    SweepSummary,
    ma_crossover_configs,
    momentum_configs,
    persist_sweep,
    run_sweep,
    summarize_sweep,
)
from app.services.backtest.strategies import (
    BuyAndHoldStrategy,
    EqualWeightStrategy,
    MACrossoverStrategy,
    MomentumStrategy,
    ReversalStrategy,
)
from app.services.backtest.strategies.registry import get_strategy
from app.services.backtest.types import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    PriceField,
    RebalanceFreq,
    Trade,
)
from app.services.backtest.validation import (
    TimeSplit,
    TrainForwardValidation,
    run_train_forward_validation,
    split_prices_by_time,
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
    "ParamImpact",
    "PriceField",
    "RebalanceFreq",
    "ReversalStrategy",
    "Strategy",
    "SweepPoint",
    "SweepSummary",
    "TimeSplit",
    "Trade",
    "TrainForwardValidation",
    "build_equity_curve_points",
    "build_trade_points",
    "compute_benchmark_comparison",
    "compute_result_metrics",
    "compute_risk_metrics",
    "execute_backtest_run",
    "get_strategy",
    "load_benchmark_prices",
    "load_prices",
    "ma_crossover_configs",
    "momentum_configs",
    "persist_sweep",
    "run_backtest",
    "run_sweep",
    "run_train_forward_validation",
    "split_prices_by_time",
    "summarize_sweep",
    "to_metrics_orm",
]
