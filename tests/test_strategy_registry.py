"""Strategy registry unit tests (FRA-37) — 纯单元,无 DB。"""

from __future__ import annotations

import pytest
from app.services.backtest.strategies import (
    BuyAndHoldStrategy,
    EqualWeightStrategy,
    MACrossoverStrategy,
    MomentumStrategy,
    ReversalStrategy,
)
from app.services.backtest.strategies.registry import get_strategy


def test_get_strategy_returns_correct_class() -> None:
    assert isinstance(get_strategy("buy_hold"), BuyAndHoldStrategy)
    assert isinstance(get_strategy("equal_weight"), EqualWeightStrategy)
    assert isinstance(get_strategy("ma_crossover"), MACrossoverStrategy)
    assert isinstance(get_strategy("momentum"), MomentumStrategy)
    assert isinstance(get_strategy("reversal"), ReversalStrategy)


def test_get_strategy_passes_params() -> None:
    ma = get_strategy("ma_crossover", {"fast": 3, "slow": 10})
    assert ma._fast == 3  # type: ignore[attr-defined]
    assert ma._slow == 10  # type: ignore[attr-defined]
    mom = get_strategy("momentum", {"lookback": 21, "top_k": 3})
    assert mom._lookback == 21  # type: ignore[attr-defined]
    assert mom._top_k == 3  # type: ignore[attr-defined]


def test_get_strategy_default_params_when_none() -> None:
    ma = get_strategy("ma_crossover")  # 默认 fast=5, slow=20
    assert ma._fast == 5  # type: ignore[attr-defined]
    assert ma._slow == 20  # type: ignore[attr-defined]


def test_get_strategy_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown strategy"):
        get_strategy("nonexistent")
