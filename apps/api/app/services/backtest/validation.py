"""Time-based train -> forward validation helpers for backtests (FRA-39).

Financial time series must be validated by chronology, not random splits. This
module keeps the Week 2 version deliberately small: choose the best candidate
configuration on a train window, then re-run exactly that configuration on a
later forward window. It is pure computation and does not persist runs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date

import pandas as pd

from app.services.backtest.engine import run_backtest
from app.services.backtest.metrics import compute_result_metrics
from app.services.backtest.protocols import Strategy
from app.services.backtest.types import BacktestConfig, BacktestMetrics, BacktestResult


@dataclass(frozen=True, slots=True)
class TimeSplit:
    """Chronological validation windows.

    ``train_end`` must be strictly before ``forward_start`` so the selected
    candidate cannot use any forward-period observation while being chosen.
    """

    train_start: date
    train_end: date
    forward_start: date
    forward_end: date


@dataclass(frozen=True, slots=True)
class TrainForwardValidation:
    """Result of selecting on train and evaluating on forward."""

    selected_config: BacktestConfig
    train_result: BacktestResult
    forward_result: BacktestResult
    train_gross_metrics: BacktestMetrics
    train_net_metrics: BacktestMetrics
    forward_gross_metrics: BacktestMetrics
    forward_net_metrics: BacktestMetrics


StrategyFactory = Callable[[BacktestConfig], Strategy]


def split_prices_by_time(
    prices: pd.DataFrame, split: TimeSplit
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a price wide-frame into non-overlapping train and forward windows."""
    _validate_split(split)
    if prices.empty:
        raise ValueError("prices must not be empty")

    idx_dates = pd.Series(prices.index.date, index=prices.index)
    train = prices.loc[(idx_dates >= split.train_start) & (idx_dates <= split.train_end)]
    forward = prices.loc[(idx_dates >= split.forward_start) & (idx_dates <= split.forward_end)]
    if train.empty:
        raise ValueError("train window contains no price rows")
    if forward.empty:
        raise ValueError("forward window contains no price rows")
    return train, forward


def run_train_forward_validation(
    prices: pd.DataFrame,
    candidate_configs: Sequence[BacktestConfig],
    strategy_factory: StrategyFactory,
    split: TimeSplit,
) -> TrainForwardValidation:
    """Select a candidate on train net Sharpe, then evaluate it on forward data.

    The selected configuration is cloned with the forward dates before the
    forward run, preserving strategy parameters, rebalance, price field, costs,
    universe, and benchmark assumptions.
    """
    if not candidate_configs:
        raise ValueError("candidate_configs must not be empty")

    train_prices, forward_prices = split_prices_by_time(prices, split)

    best: (
        tuple[float, float, BacktestConfig, BacktestResult, BacktestMetrics, BacktestMetrics] | None
    )
    best = None
    for config in candidate_configs:
        train_config = replace(config, start=split.train_start, end=split.train_end)
        train_result = run_backtest(train_prices, strategy_factory(train_config), train_config)
        train_gross, train_net = compute_result_metrics(train_result)
        score = (train_net.sharpe_ratio, train_net.annual_return)
        if best is None or score > (best[0], best[1]):
            best = (
                train_net.sharpe_ratio,
                train_net.annual_return,
                train_config,
                train_result,
                train_gross,
                train_net,
            )

    assert best is not None
    _, _, selected_train_config, train_result, train_gross, train_net = best
    forward_config = replace(
        selected_train_config,
        start=split.forward_start,
        end=split.forward_end,
    )
    forward_result = run_backtest(forward_prices, strategy_factory(forward_config), forward_config)
    forward_gross, forward_net = compute_result_metrics(forward_result)

    return TrainForwardValidation(
        selected_config=forward_config,
        train_result=train_result,
        forward_result=forward_result,
        train_gross_metrics=train_gross,
        train_net_metrics=train_net,
        forward_gross_metrics=forward_gross,
        forward_net_metrics=forward_net,
    )


def _validate_split(split: TimeSplit) -> None:
    if split.train_start > split.train_end:
        raise ValueError("train_start must be <= train_end")
    if split.forward_start > split.forward_end:
        raise ValueError("forward_start must be <= forward_end")
    if split.train_end >= split.forward_start:
        raise ValueError("train_end must be before forward_start")
