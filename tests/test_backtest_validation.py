"""Time-based train -> forward validation tests (FRA-39)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest
from app.services.backtest.strategies import BuyAndHoldStrategy, EqualWeightStrategy
from app.services.backtest.types import BacktestConfig, RebalanceFreq
from app.services.backtest.validation import (
    TimeSplit,
    run_train_forward_validation,
    split_prices_by_time,
)


def _prices() -> pd.DataFrame:
    idx = pd.date_range("2024-01-02", periods=8, freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "A": [100.0, 104.0, 108.0, 112.0, 116.0, 116.0, 115.0, 114.0],
            "B": [100.0, 100.0, 100.0, 100.0, 100.0, 103.0, 106.0, 109.0],
        },
        index=idx,
    )


def _config(**overrides: Any) -> BacktestConfig:
    fields: dict[str, Any] = {
        "universe": ("A", "B"),
        "start": date(2024, 1, 2),
        "end": date(2024, 1, 11),
        "strategy_name": "buy_hold",
        "initial_capital": 100_000.0,
        "cost_bps": 0.0,
        "rebalance": RebalanceFreq.DAILY,
    }
    fields.update(overrides)
    return BacktestConfig(**fields)


def test_split_prices_by_time_produces_non_overlapping_windows() -> None:
    split = TimeSplit(
        train_start=date(2024, 1, 2),
        train_end=date(2024, 1, 5),
        forward_start=date(2024, 1, 8),
        forward_end=date(2024, 1, 11),
    )

    train, forward = split_prices_by_time(_prices(), split)

    assert train.index.max().date() == date(2024, 1, 5)
    assert forward.index.min().date() == date(2024, 1, 8)
    assert set(train.index).isdisjoint(set(forward.index))


def test_split_prices_by_time_rejects_overlap() -> None:
    split = TimeSplit(
        train_start=date(2024, 1, 2),
        train_end=date(2024, 1, 8),
        forward_start=date(2024, 1, 8),
        forward_end=date(2024, 1, 11),
    )

    with pytest.raises(ValueError, match="train_end must be before forward_start"):
        split_prices_by_time(_prices(), split)


def test_train_forward_validation_selects_on_train_then_evaluates_forward() -> None:
    split = TimeSplit(
        train_start=date(2024, 1, 2),
        train_end=date(2024, 1, 5),
        forward_start=date(2024, 1, 8),
        forward_end=date(2024, 1, 11),
    )
    candidates = [
        _config(strategy_name="buy_hold", strategy_params={"weights": {"A": 1.0, "B": 0.0}}),
        _config(strategy_name="equal_weight"),
    ]

    def strategy_factory(config: BacktestConfig) -> BuyAndHoldStrategy | EqualWeightStrategy:
        if config.strategy_name == "buy_hold":
            weights = config.strategy_params.get("weights")
            assert isinstance(weights, dict)
            return BuyAndHoldStrategy(weights=weights)
        if config.strategy_name == "equal_weight":
            return EqualWeightStrategy()
        raise AssertionError(config.strategy_name)

    validation = run_train_forward_validation(_prices(), candidates, strategy_factory, split)

    assert validation.selected_config.strategy_name == "buy_hold"
    assert validation.selected_config.start == split.forward_start
    assert validation.selected_config.end == split.forward_end
    assert validation.train_result.equity_curve.index.max().date() == split.train_end
    assert validation.forward_result.equity_curve.index.min().date() == split.forward_start
    assert validation.train_net_metrics.sharpe_ratio >= 0.0
    assert (
        validation.forward_net_metrics.annual_return <= validation.train_net_metrics.annual_return
    )
