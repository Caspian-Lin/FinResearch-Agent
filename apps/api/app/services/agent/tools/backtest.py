"""Backtest agent tools — create + execute and read-back (FRA-87).

Wraps the existing backtest execution pipeline. ``RunBacktestTool`` creates a
``BacktestRun`` row then calls ``execute_backtest_run`` directly (synchronous,
no RQ enqueue) — the tool runs inside the Orchestrator's step lifecycle.
``ReadBacktestTool`` returns a compact status + metrics summary.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.backtest import BacktestMetrics, BacktestRun
from app.schemas.agent import STRATEGY_NAMES
from app.services.agent.tools.protocol import (
    ToolError,
    ToolErrorKind,
    ToolResult,
    run_tool_safely,
)
from app.services.agent.tools.registry import _register

_ALLOWED_REBALANCE = frozenset({"daily", "weekly", "monthly"})
_ALLOWED_PRICE_FIELDS = frozenset({"raw", "adjusted"})


class RunBacktestTool:
    """``run_backtest`` — create + execute a backtest run synchronously.

    Input: ``{"universe": ["uuid", ...], "strategy_name": "momentum", "start": "...",
    "end": "...", "strategy_params": {...}, "cost_bps": 10.0, "rebalance": "monthly",
    "price_field": "adjusted", "benchmark_asset_id": "uuid", "initial_capital": 100000}``
    Output: ``{"run_id": "uuid", "status": "success", "equity_points": 756}``

    Side-effect, NOT idempotent (each call creates a new run).
    """

    name = "run_backtest"
    role = "backtest"
    version = "1.0"
    allowed_callers = frozenset({"backtest_agent"})
    has_side_effects = True
    idempotent = False
    timeout_seconds = 900

    def execute(self, params: dict[str, Any], *, db: Session) -> ToolResult:
        return run_tool_safely(self.name, self.version, lambda: self._run(params, db))

    def _run(self, params: dict[str, Any], db: Session) -> ToolResult:
        # ── Validate input ──────────────────────────────────────────────
        universe_raw = params.get("universe")
        if not isinstance(universe_raw, list) or not universe_raw:
            return ToolResult.fail(
                self.name,
                ToolError.of(
                    ToolErrorKind.VALIDATION, "universe must be a non-empty list of asset UUIDs"
                ),
            )

        strategy_name = params.get("strategy_name")
        if not isinstance(strategy_name, str) or strategy_name not in STRATEGY_NAMES:
            return ToolResult.fail(
                self.name,
                ToolError.of(
                    ToolErrorKind.VALIDATION,
                    f"unknown strategy {strategy_name!r}; allowed: {sorted(STRATEGY_NAMES)}",
                ),
            )

        rebalance = params.get("rebalance", "daily")
        if rebalance not in _ALLOWED_REBALANCE:
            return ToolResult.fail(
                self.name,
                ToolError.of(
                    ToolErrorKind.VALIDATION,
                    f"rebalance must be one of {sorted(_ALLOWED_REBALANCE)}",
                ),
            )

        price_field = params.get("price_field", "adjusted")
        if price_field not in _ALLOWED_PRICE_FIELDS:
            return ToolResult.fail(
                self.name,
                ToolError.of(
                    ToolErrorKind.VALIDATION,
                    f"price_field must be one of {sorted(_ALLOWED_PRICE_FIELDS)}",
                ),
            )

        start = _parse_date(params.get("start"))
        end = _parse_date(params.get("end"))
        if start is None or end is None:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "start and end are required (YYYY-MM-DD)"),
            )
        if start > end:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "start must be <= end"),
            )

        try:
            universe_uuids = [uuid.UUID(str(u)) for u in universe_raw]
        except (ValueError, TypeError):
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "universe entries must be valid UUIDs"),
            )

        benchmark_raw = params.get("benchmark_asset_id")
        benchmark_id: uuid.UUID | None = None
        if benchmark_raw is not None:
            try:
                benchmark_id = uuid.UUID(str(benchmark_raw))
            except (ValueError, TypeError):
                return ToolResult.fail(
                    self.name,
                    ToolError.of(ToolErrorKind.VALIDATION, "benchmark_asset_id must be a UUID"),
                )

        cost_bps = float(params.get("cost_bps", 0.0))
        initial_capital = float(params.get("initial_capital", 100_000.0))
        strategy_params = params.get("strategy_params", {})
        if not isinstance(strategy_params, dict):
            strategy_params = {}

        # ── Create BacktestRun row ──────────────────────────────────────
        config_json: dict[str, Any] = {
            "universe": [str(u) for u in universe_uuids],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "strategy_name": strategy_name,
            "initial_capital": initial_capital,
            "cost_bps": cost_bps,
            "rebalance": rebalance,
            "price_field": price_field,
            "benchmark": str(benchmark_id) if benchmark_id else None,
            "strategy_params": strategy_params,
        }

        run = BacktestRun(
            user_id=uuid.UUID(params.get("user_id", "00000000-0000-0000-0000-000000000000")),
            name=params.get("name", f"agent-{strategy_name}-{start}"),
            strategy_type=strategy_name,
            config_json=config_json,
            benchmark_asset_id=benchmark_id,
            start_date=start,
            end_date=end,
            price_field=price_field,
            status="pending",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        # ── Execute (uses its own session) ──────────────────────────────
        from app.services.backtest.execution import execute_backtest_run

        result_dict = execute_backtest_run(str(run_id))

        # ── Read back fresh (execute used its own session) ───────────────
        db.expire_all()
        finished_run = db.get(BacktestRun, run_id)
        if finished_run is None:
            return ToolResult.fail(
                self.name,
                ToolError.of(
                    ToolErrorKind.INTERNAL, f"backtest run {run_id} disappeared after execution"
                ),
                tool_version=self.version,
            )

        if finished_run.status == "failed":
            return ToolResult.fail(
                self.name,
                ToolError.of(
                    ToolErrorKind.INTERNAL,
                    f"backtest failed: {finished_run.error_message or 'unknown error'}",
                    retriable=True,
                ),
                tool_version=self.version,
            )

        return ToolResult.ok(
            self.name,
            {
                "run_id": str(run_id),
                "status": run.status,
                "strategy": strategy_name,
                "equity_points": result_dict.get("equity_points", 0),
                "has_benchmark": result_dict.get("benchmark", False),
                "window": {"start": start.isoformat(), "end": end.isoformat()},
                "universe_size": len(universe_uuids),
                "cost_bps": cost_bps,
                "rebalance": rebalance,
            },
            tool_version=self.version,
            side_effect_ref=f"backtest_run:{run_id}",
        )


class ReadBacktestTool:
    """``read_backtest`` — read status + metrics for a completed backtest.

    Input: ``{"run_id": "uuid"}``
    Output: ``{"run_id": "uuid", "status": "success", "metrics": {...}, ...}``

    Read-only, idempotent.
    """

    name = "read_backtest"
    role = "backtest"
    version = "1.0"
    allowed_callers = frozenset({"backtest_agent", "risk_agent", "report_agent"})
    has_side_effects = False
    idempotent = True
    timeout_seconds = 30

    def execute(self, params: dict[str, Any], *, db: Session) -> ToolResult:
        return run_tool_safely(self.name, self.version, lambda: self._run(params, db))

    def _run(self, params: dict[str, Any], db: Session) -> ToolResult:
        run_id_raw = params.get("run_id")
        if not isinstance(run_id_raw, str):
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "run_id is required"),
            )
        try:
            run_id = uuid.UUID(run_id_raw)
        except ValueError:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, f"invalid run_id: {run_id_raw}"),
            )

        run = db.get(BacktestRun, run_id)
        if run is None:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.NOT_FOUND, f"backtest run {run_id} not found"),
            )

        # Read metrics (1:1 with run).
        metrics_orm = db.get(BacktestMetrics, run_id)
        metrics: dict[str, Any] | None = None
        if metrics_orm is not None:
            metrics = {
                "gross_annual_return": float(metrics_orm.gross_annual_return)
                if metrics_orm.gross_annual_return is not None
                else None,
                "net_annual_return": float(metrics_orm.net_annual_return)
                if metrics_orm.net_annual_return is not None
                else None,
                "net_sharpe_ratio": float(metrics_orm.net_sharpe_ratio)
                if metrics_orm.net_sharpe_ratio is not None
                else None,
                "gross_sharpe_ratio": float(metrics_orm.gross_sharpe_ratio)
                if metrics_orm.gross_sharpe_ratio is not None
                else None,
                "net_max_drawdown": float(metrics_orm.net_max_drawdown)
                if metrics_orm.net_max_drawdown is not None
                else None,
                "gross_max_drawdown": float(metrics_orm.gross_max_drawdown)
                if metrics_orm.gross_max_drawdown is not None
                else None,
                "net_turnover": float(metrics_orm.net_turnover)
                if metrics_orm.net_turnover is not None
                else None,
            }

        return ToolResult.ok(
            self.name,
            {
                "run_id": str(run_id),
                "status": run.status,
                "strategy": run.strategy_type,
                "has_benchmark": run.benchmark_asset_id is not None,
                "start_date": run.start_date.isoformat(),
                "end_date": run.end_date.isoformat(),
                "metrics": metrics,
                "error": run.error_message,
            },
            tool_version=self.version,
        )


def _parse_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        try:
            return date.fromisoformat(val[:10])
        except ValueError:
            return None
    return None


# Register tools.
_register(RunBacktestTool())
_register(ReadBacktestTool())
