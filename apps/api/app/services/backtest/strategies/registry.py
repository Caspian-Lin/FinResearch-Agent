"""Strategy registry — config_json.strategy_name → Strategy instance (FRA-37).

backtest worker 据此把 ``run.config_json`` 的策略名解析成具体策略实例。新增
策略只需在 ``_REGISTRY`` 注册一行。与 FRA-29~32 的 5 个策略对接。
"""

from __future__ import annotations

from typing import Any

from app.services.backtest.protocols import Strategy
from app.services.backtest.strategies import (
    BuyAndHoldStrategy,
    EqualWeightStrategy,
    MACrossoverStrategy,
    MomentumStrategy,
    ReversalStrategy,
)

#: 策略名 → 构造类。``config_json.strategy_name`` 必须命中其一;参数取自
#: ``config_json.strategy_params``(如 fast/slow、lookback/top_k)。
_REGISTRY: dict[str, type] = {
    "buy_hold": BuyAndHoldStrategy,
    "equal_weight": EqualWeightStrategy,
    "ma_crossover": MACrossoverStrategy,
    "momentum": MomentumStrategy,
    "reversal": ReversalStrategy,
}


def get_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    """按名 + 参数构造策略实例。

    Args:
        name: 策略名(``buy_hold`` / ``equal_weight`` / ``ma_crossover`` /
            ``momentum`` / ``reversal``)。
        params: 透传给构造器的策略参数(如 ``{"fast": 5, "slow": 20}``);None
            或空 → 各策略默认。

    Raises:
        ValueError: 未知策略名。
    """
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"unknown strategy {name!r}; expected one of {sorted(_REGISTRY)}")
    strategy: Strategy = cls(**(params or {}))
    return strategy
