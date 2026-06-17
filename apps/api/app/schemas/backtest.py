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

from pydantic import BaseModel, ConfigDict


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
