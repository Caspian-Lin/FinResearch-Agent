"""Pydantic v2 read schemas for backtest results (FRA-26).

Mirror the ORM models in ``app/models/backtest.py`` 1:1 so
``model_config = ConfigDict(from_attributes=True)`` round-trips an ORM object
to its API representation without manual mapping. The backtest API (later
issue) returns these.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BacktestRunRead(BaseModel):
    """Serialized backtest run with its full config snapshot."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    strategy_type: str
    config_json: dict[str, Any]
    benchmark_asset_id: uuid.UUID | None
    start_date: date
    end_date: date
    price_field: str
    status: str
    error_message: str | None
    run_kind: str
    created_at: datetime


class BacktestMetricsRead(BaseModel):
    """Gross + net metric sets for one run (1:1 with ``BacktestRunRead``)."""

    model_config = ConfigDict(from_attributes=True)

    backtest_run_id: uuid.UUID
    gross_annual_return: Decimal | None
    gross_volatility: Decimal | None
    gross_sharpe_ratio: Decimal | None
    gross_max_drawdown: Decimal | None
    gross_calmar_ratio: Decimal | None
    gross_turnover: Decimal | None
    gross_win_rate: Decimal | None
    gross_beta: Decimal | None
    gross_correlation: Decimal | None
    net_annual_return: Decimal | None
    net_volatility: Decimal | None
    net_sharpe_ratio: Decimal | None
    net_max_drawdown: Decimal | None
    net_calmar_ratio: Decimal | None
    net_turnover: Decimal | None
    net_win_rate: Decimal | None
    net_beta: Decimal | None
    net_correlation: Decimal | None


class EquityCurvePointRead(BaseModel):
    """One point of a run's equity / daily-return / drawdown curve."""

    model_config = ConfigDict(from_attributes=True)

    backtest_run_id: uuid.UUID
    series_kind: str
    time: datetime
    equity: Decimal
    daily_return: Decimal | None
    drawdown: Decimal | None


class TradeRead(BaseModel):
    """One rebalance fill."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    backtest_run_id: uuid.UUID
    time: datetime
    asset_id: uuid.UUID
    side: str
    quantity: Decimal
    price: Decimal
    cost: Decimal
    created_at: datetime


# --- FRA-36: backtest API request / response schemas -----------------------


class BacktestCreateRequest(BaseModel):
    """Payload for ``POST /backtest``.

    ``universe`` is a non-empty list of asset UUIDs (validated to exist);
    ``strategy_name`` must be a registered strategy; ``benchmark_asset_id`` is
    optional but, if given, must reference an existing asset. ``config_json``
    stores the full snapshot for reproducibility (§11.3 第 6 条).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    strategy_name: str
    universe: list[uuid.UUID] = Field(min_length=1)
    start: date
    end: date
    benchmark_asset_id: uuid.UUID | None = None
    initial_capital: float = Field(default=100_000.0, gt=0)
    cost_bps: float = Field(default=0.0, ge=0)
    rebalance: str = "daily"  # daily | weekly | monthly
    price_field: str = "adjusted"  # raw | adjusted
    strategy_params: dict[str, Any] = Field(default_factory=dict)


class BacktestEnqueueResponse(BaseModel):
    """202 response after a backtest run is created + enqueued."""

    run_id: uuid.UUID
    status: str = "pending"


class BacktestDetailRead(BaseModel):
    """Full result for ``GET /backtest/{run_id}``: run + metrics + curves.

    ``equity_curve`` holds both ``strategy`` and ``benchmark`` points
    (distinguished by ``series_kind``, FRA-41); empty until the worker finishes.
    """

    run: BacktestRunRead
    metrics: BacktestMetricsRead | None = None
    equity_curve: list[EquityCurvePointRead] = Field(default_factory=list)


class BacktestListResponse(BaseModel):
    """Paginated list of the caller's runs (``GET /backtest``)."""

    items: list[BacktestRunRead]
    total: int
