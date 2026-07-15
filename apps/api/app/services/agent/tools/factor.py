"""Factor agent tools — compute/persist and IC evaluation (FRA-87).

Wraps the existing factor service layer. The tools enforce the FRA-84
allowlist (``TECHNICAL_FACTOR_NAMES``) and return compact summaries — never
raw DataFrames — so the LLM context isn't flooded with price series.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.schemas.agent import TECHNICAL_FACTOR_NAMES
from app.services.agent.tools.protocol import (
    ToolError,
    ToolErrorKind,
    ToolResult,
    run_tool_safely,
)
from app.services.agent.tools.registry import _register
from app.services.factors.evaluation import evaluate_ic, forward_returns
from app.services.factors.service import compute_and_store_factors, read_factor_values


class ComputeFactorTool:
    """``compute_factor`` — compute + persist factor values for a universe.

    Input: ``{"asset_ids": [...], "factor_names": ["momentum_126"], "start": "...", "end": "...", "source": "yfinance", "price_field": "adjusted"}``
    Output: ``{"rows_persisted": 1234, "factors": ["momentum_126"]}``

    Side-effect (upsert), idempotent. Wraps ``compute_and_store_factors``,
    which owns the anti-look-ahead rolling windows and NaN-skip rules.
    """

    name = "compute_factor"
    role = "factor"
    version = "1.0"
    allowed_callers = frozenset({"factor_agent"})
    has_side_effects = True
    idempotent = True
    timeout_seconds = 600

    def execute(self, params: dict[str, Any], *, db: Session) -> ToolResult:
        return run_tool_safely(self.name, self.version, lambda: self._run(params, db))

    def _run(self, params: dict[str, Any], db: Session) -> ToolResult:
        asset_ids_raw = params.get("asset_ids")
        if not isinstance(asset_ids_raw, list) or not asset_ids_raw:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "asset_ids must be a non-empty list"),
            )

        factor_names = params.get("factor_names")
        if not isinstance(factor_names, list) or not factor_names:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "factor_names must be a non-empty list"),
            )

        # Allowlist check.
        unknown = [f for f in factor_names if f not in TECHNICAL_FACTOR_NAMES]
        if unknown:
            return ToolResult.fail(
                self.name,
                ToolError.of(
                    ToolErrorKind.VALIDATION,
                    f"unknown factor names {unknown}; allowed: {sorted(TECHNICAL_FACTOR_NAMES)}",
                ),
            )

        try:
            asset_uuids = [uuid.UUID(str(a)) for a in asset_ids_raw]
        except (ValueError, TypeError):
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "asset_ids must be UUIDs"),
            )

        start = _parse_date(params.get("start"))
        end = _parse_date(params.get("end"))
        if start is None or end is None:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "start and end are required (YYYY-MM-DD)"),
            )

        source = params.get("source", "yfinance")
        price_field = params.get("price_field", "adjusted")

        rows = compute_and_store_factors(
            db,
            universe=asset_uuids,
            source=source,
            start=start,
            end=end,
            price_field=price_field,
            factor_names=factor_names,
        )

        return ToolResult.ok(
            self.name,
            {
                "rows_persisted": rows,
                "factors": factor_names,
                "universe_size": len(asset_uuids),
                "source": source,
                "window": {"start": start.isoformat(), "end": end.isoformat()},
            },
            tool_version=self.version,
            side_effect_ref=f"factor_compute:{len(asset_uuids)}x{len(factor_names)}",
        )


class EvaluateFactorTool:
    """``evaluate_factor`` — read-only IC / significance evaluation.

    Input: ``{"asset_ids": [...], "factor_name": "momentum_126", "start": "...", "end": "...", "source": "yfinance", "horizon": 21, "price_field": "adjusted"}``
    Output: ``{"ic_mean": 0.05, "icir": 0.8, "t_stat": 2.1, ...}``

    Read-only, idempotent. Wraps ``read_factor_values`` + ``forward_returns``
    + ``evaluate_ic``. Forward returns are evaluation-only and never feed a
    ``t``-day strategy decision.
    """

    name = "evaluate_factor"
    role = "factor"
    version = "1.0"
    allowed_callers = frozenset({"factor_agent", "risk_agent"})
    has_side_effects = False
    idempotent = True
    timeout_seconds = 300

    def execute(self, params: dict[str, Any], *, db: Session) -> ToolResult:
        return run_tool_safely(self.name, self.version, lambda: self._run(params, db))

    def _run(self, params: dict[str, Any], db: Session) -> ToolResult:
        factor_name = params.get("factor_name")
        if not isinstance(factor_name, str):
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "factor_name is required"),
            )
        if factor_name not in TECHNICAL_FACTOR_NAMES:
            return ToolResult.fail(
                self.name,
                ToolError.of(
                    ToolErrorKind.VALIDATION,
                    f"unknown factor {factor_name!r}; allowed: {sorted(TECHNICAL_FACTOR_NAMES)}",
                ),
            )

        asset_ids_raw = params.get("asset_ids")
        if not isinstance(asset_ids_raw, list) or not asset_ids_raw:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "asset_ids must be a non-empty list"),
            )

        try:
            asset_ids = [uuid.UUID(str(a)) for a in asset_ids_raw]
        except (ValueError, TypeError):
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "asset_ids must be UUIDs"),
            )

        start = _parse_date(params.get("start"))
        end = _parse_date(params.get("end"))
        if start is None or end is None:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "start and end are required"),
            )

        source = params.get("source", "yfinance")
        horizon = params.get("horizon", 21)
        if not isinstance(horizon, int) or horizon < 1:
            horizon = 21

        # Read stored factor values.
        factor_df = read_factor_values(
            db,
            asset_ids=asset_ids,
            factor_name=factor_name,
            source=source,
            start=start,
            end=end,
        )
        if factor_df.empty:
            return ToolResult.fail(
                self.name,
                ToolError.of(
                    ToolErrorKind.INSUFFICIENT_DATA,
                    f"no stored factor values for {factor_name!r} in the given window",
                ),
            )

        # Read prices for forward returns.
        from app.services.backtest.prices import load_prices

        price_field = params.get("price_field", "adjusted")
        prices = load_prices(
            db,
            universe=asset_ids,
            source=source,
            start=start,
            end=end,
            price_field=price_field,
        )
        if prices.empty:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.INSUFFICIENT_DATA, "no price data for forward returns"),
            )

        # Align columns.
        common = [c for c in factor_df.columns if c in prices.columns]
        if not common:
            return ToolResult.fail(
                self.name,
                ToolError.of(
                    ToolErrorKind.INSUFFICIENT_DATA,
                    "no overlapping assets between factor and price data",
                ),
            )

        fwd = forward_returns(prices[common], horizon=horizon)
        # Align index.
        common_idx = factor_df[common].index.intersection(fwd.index)
        if len(common_idx) < 10:
            return ToolResult.fail(
                self.name,
                ToolError.of(
                    ToolErrorKind.INSUFFICIENT_DATA,
                    f"only {len(common_idx)} overlapping dates; need ≥10 for IC evaluation",
                ),
            )

        ic_result = evaluate_ic(factor_df[common].loc[common_idx], fwd.loc[common_idx])
        s = ic_result.summary

        return ToolResult.ok(
            self.name,
            {
                "factor_name": factor_name,
                "horizon": horizon,
                "ic_mean": round(s.mean, 6),
                "icir": round(s.icir, 6),
                "t_stat": round(s.t_stat, 4),
                "p_value": round(s.p_value, 6),
                "n": s.n,
                "positive_rate": round(s.positive_rate, 4),
                "source": source,
                "window": {"start": start.isoformat(), "end": end.isoformat()},
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
_register(ComputeFactorTool())
_register(EvaluateFactorTool())
