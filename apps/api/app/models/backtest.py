"""Backtest result ORM models — runs, metrics, equity curve, trades (FRA-26).

Stores the outputs of a backtest run for reproducibility (config snapshot),
benchmark comparison, and equity/drawdown-curve + trade-detail display.

* ``backtest_runs`` is the parent — one row per run.
* ``backtest_metrics`` is 1:1 with it (``backtest_run_id`` is both PK and FK);
  a single row holds the gross (pre-cost) and net (post-cost) metric sets so
  the §11.3 第 5 条 pre/post-cost comparison is a one-row read.
* ``equity_curve`` is a TimescaleDB hypertable partitioned by ``time``
  (one point per trading day); ``time`` is in the PK to satisfy the hypertable
  partition-column requirement (mirrors ``ohlcv``).
* ``trades`` records each rebalance fill for one asset.

See ``docs/database-schema.md`` and the FRA-25 interface contract in
``docs/backtesting-methodology.md`` §接口契约.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: allowed values for ``BacktestRun.price_field`` (mirrors FRA-25 ``PriceField``).
PRICE_FIELDS = ("raw", "adjusted")
#: allowed values for ``BacktestRun.status`` (mirrors the Week 1 sync-job states).
BACKTEST_STATUSES = ("pending", "running", "success", "failed")
#: allowed values for ``EquityCurvePoint.series_kind`` (FRA-41) — distinguishes the
#: strategy's own curve from the buy & hold benchmark curve stored in the same table.
SERIES_KINDS = ("strategy", "benchmark")
#: allowed values for ``BacktestRun.run_kind`` (FRA-35) — ``backtest`` is a single
#: triggered run (POST /backtest); ``sensitivity`` marks each child run produced by a
#: parameter/cost sweep so sweep runs are queryable apart from regular backtests.
RUN_KINDS = ("backtest", "sensitivity")


class BacktestRun(Base):
    """One backtest run: metadata + full config snapshot for reproducibility.

    ``config_json`` serializes the FRA-25 ``BacktestConfig`` 1:1 (universe,
    start, end, strategy name + params, initial_capital, cost_bps, rebalance,
    price_field, benchmark) so a run can be reconstructed exactly (§11.3.6).
    ``run_kind`` (FRA-35) marks sweep-produced runs (``sensitivity``) apart from
    one-off triggered runs (``backtest``).
    """

    __tablename__ = "backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    strategy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    benchmark_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id"), nullable=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    price_field: Mapped[str] = mapped_column(String(16), nullable=False)  # raw | adjusted
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # 失败原因(FRA-37):success / running 时为 NULL;failed 时填异常摘要(≤500 字符)。
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # run_kind(FRA-35):``backtest`` = 单次触发回测;``sensitivity`` = 参数/成本 sweep
    # 产出的子 run。默认 ``backtest`` —— 既有 run 与 POST /backtest 路径不受影响,
    # sweep 入库时显式置 ``sensitivity``。
    run_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="backtest", server_default="backtest"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# The 9 §11.2 metrics are written out explicitly as gross_* + net_* columns
# below (kept flat rather than a JSON column so they stay queryable / indexable).


class BacktestMetrics(Base):
    """Risk/return metrics for one run — gross (pre-cost) + net (post-cost).

    1:1 with ``backtest_runs``. Each of the 9 §11.2 metrics appears twice:
    once gross (before ``cost_bps``) and once net (after), so pre/post-cost
    comparison is a single-row read.
    """

    __tablename__ = "backtest_metrics"

    backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backtest_runs.id"), primary_key=True
    )
    # gross (pre-cost) metric set
    gross_annual_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    gross_volatility: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    gross_sharpe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    gross_max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    gross_calmar_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    gross_turnover: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    gross_win_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    gross_beta: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    gross_correlation: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    # net (post-cost) metric set
    net_annual_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    net_volatility: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    net_sharpe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    net_max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    net_calmar_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    net_turnover: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    net_win_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    net_beta: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    net_correlation: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))


class EquityCurvePoint(Base):
    """One daily point of a run's equity curve (hypertable, partitioned by time).

    Composite PK ``(backtest_run_id, series_kind, time)`` identifies a run's curve
    and lets the buy & hold ``benchmark`` curve coexist with the ``strategy`` curve
    in the same table (FRA-41) — one row per (run, kind, day). The partition column
    ``time`` remains part of the PK (the ``ohlcv`` pattern).
    """

    __tablename__ = "equity_curve"

    backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backtest_runs.id"), primary_key=True
    )
    # strategy = the run's own curve; benchmark = the buy & hold reference (FRA-41).
    series_kind: Mapped[str] = mapped_column(
        String(16), primary_key=True, nullable=False, default="strategy", server_default="strategy"
    )
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    daily_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    drawdown: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))


class Trade(Base):
    """One rebalance fill for one asset in one run (engine-core issue writes these)."""

    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backtest_runs.id"), nullable=False
    )
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False
    )
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # buy | sell
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
