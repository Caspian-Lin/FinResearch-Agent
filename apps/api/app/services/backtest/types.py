"""Backtest data contracts — config, results, metrics (FRA-25).

This module is the single source of truth for the in-memory shapes that flow
between the strategy, engine, and risk-metric layers. It is a typed *stub*:
the types are final, but no backtest logic lives here. The engine ``run``
loop, weight calculation, and metric computation are delivered by later
issues (engine-core, per-strategy, risk-metrics).

Contracts mirror ``docs/backtesting-methodology.md`` §接口契约 and align with
the ``packages/shared`` TypeScript types (``BacktestMetrics`` / ``BacktestRun``)
so the frontend can consume results without a second translation layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

import pandas as pd


class PriceField(StrEnum):
    """Which OHLCV series the engine prices the universe with.

    Mirrors the two price columns persisted by the FRA-8 yfinance adapter:
    ``ohlcv.close`` (raw) and ``ohlcv.adjusted_close`` (split/dividend
    adjusted). ADJUSTED is the default so corporate-action jumps do not
    contaminate returns.
    """

    RAW = "raw"  # ohlcv.close
    ADJUSTED = "adjusted"  # ohlcv.adjusted_close


class RebalanceFreq(StrEnum):
    """How often target weights are re-applied.

    Values map to ``exchange_calendars`` / pandas offset aliases in the engine
    (DAILY → business day, WEEKLY → Friday close, MONTHLY → month end); the
    engine-core issue owns the actual rebalance-date selection.
    """

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


# pandas offset alias for each rebalance frequency. Consumed by the engine-core
# issue when it selects rebalance dates; kept here so config ↔ freq mapping
# lives in one auditable place (see §接口契约).
REBALANCE_FREQ_OFFSET: Mapping[RebalanceFreq, str] = {
    RebalanceFreq.DAILY: "B",  # business day
    RebalanceFreq.WEEKLY: "W-FRI",  # week ending Friday
    RebalanceFreq.MONTHLY: "ME",  # month end
}


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Immutable, fully-recorded parameters for one backtest run.

    Every field is part of the reproducibility record (§11.3 第 6 条): two runs
    with an equal ``BacktestConfig`` and equal price input must produce an equal
    ``BacktestResult``. The config is frozen (fields cannot be reassigned) and
    safe to log; two configs compare equal field-by-field. ``universe`` is a
    tuple (not list) for immutability. ``cost_bps`` is the *one-way* transaction
    cost in basis points; the engine applies it to both buys and sells, enabling
    the pre/post-cost comparison required by §11.3 第 5 条.
    """

    universe: tuple[str, ...]
    start: date
    end: date
    strategy_name: str
    initial_capital: float = 100_000.0
    cost_bps: float = 0.0
    rebalance: RebalanceFreq = RebalanceFreq.DAILY
    price_field: PriceField = PriceField.ADJUSTED
    benchmark: str | None = None
    strategy_params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Trade:
    """One rebalance event for one asset: the weight delta and resulting turnover.

    ``turnover`` is the one-way traded fraction ``|weight_after - weight_before|``;
    the engine sums per-asset turnover and multiplies by ``cost_bps`` to apply
    transaction costs.
    """

    date: pd.Timestamp
    asset_id: str
    weight_before: float
    weight_after: float
    turnover: float


@dataclass(slots=True)
class BacktestMetrics:
    """Risk/return metrics for one run.

    The field set is final; *values* are populated by the risk-metrics issue,
    not here. It is kept 1:1 with ``packages/shared`` ``BacktestMetrics`` so a
    serialized ``BacktestRun`` round-trips to the frontend unchanged.
    """

    annual_return: float
    volatility: float
    sharpe_ratio: float
    max_drawdown: float
    calmar_ratio: float
    turnover: float
    win_rate: float
    beta: float
    correlation: float


@dataclass(slots=True)
class BacktestResult:
    """Output of ``BacktestEngine.run``.

    All time-indexed series share the UTC-midnight ``DatetimeIndex`` defined in
    the price-DataFrame convention. ``metrics`` is ``None`` until the
    risk-metrics issue computes it; callers must treat a missing ``metrics`` as
    "not yet evaluated" rather than zero.
    """

    config: BacktestConfig
    equity_curve: pd.Series
    daily_returns: pd.Series
    turnover: pd.Series
    positions: pd.DataFrame
    trades: list[Trade] = field(default_factory=list)
    metrics: BacktestMetrics | None = None
