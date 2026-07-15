"""Data agent tools — asset resolution and OHLCV coverage check (FRA-87).

These are read-only tools that the Data Agent (and the Planner) use to map
symbols to asset UUIDs and detect data gaps before triggering a sync.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.ohlcv import Ohlcv
from app.services.agent.tools.protocol import (
    ToolError,
    ToolErrorKind,
    ToolResult,
    run_tool_safely,
)
from app.services.agent.tools.registry import _register


class ResolveAssetsTool:
    """``resolve_assets`` — map input symbols to asset UUIDs + data source.

    Input: ``{"symbols": ["NVDA", "AMD"]}``
    Output: ``{"resolved": [...], "unresolved": [...], "ambiguous": [...]}``

    Read-only, idempotent. Detects ambiguity (same symbol on multiple
    exchanges) and unknown symbols.
    """

    name = "resolve_assets"
    role = "data"
    version = "1.0"
    allowed_callers = frozenset({"research_planner", "data_agent"})
    has_side_effects = False
    idempotent = True
    timeout_seconds = 30

    def execute(self, params: dict[str, Any], *, db: Session) -> ToolResult:
        return run_tool_safely(self.name, self.version, lambda: self._run(params, db))

    def _run(self, params: dict[str, Any], db: Session) -> ToolResult:
        symbols = params.get("symbols")
        if not isinstance(symbols, list) or not symbols:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "symbols must be a non-empty list"),
            )

        resolved: list[dict[str, Any]] = []
        unresolved: list[str] = []
        ambiguous: list[dict[str, Any]] = []

        for sym in symbols:
            if not isinstance(sym, str) or not sym.strip():
                continue
            rows = list(
                db.execute(select(Asset).where(Asset.symbol == sym.strip().upper())).scalars()
            )
            if not rows:
                unresolved.append(sym.strip().upper())
            elif len(rows) > 1:
                ambiguous.append(
                    {
                        "symbol": sym.strip().upper(),
                        "exchanges": [r.exchange for r in rows],
                    }
                )
            else:
                r = rows[0]
                resolved.append(
                    {
                        "symbol": r.symbol,
                        "asset_id": str(r.id),
                        "data_source": r.data_source,
                        "exchange": r.exchange,
                    }
                )

        return ToolResult.ok(
            self.name,
            {
                "resolved": resolved,
                "unresolved": unresolved,
                "ambiguous": ambiguous,
                "count": len(resolved),
            },
            tool_version=self.version,
        )


class CheckCoverageTool:
    """``check_coverage`` — inspect OHLCV bar coverage for a universe + window.

    Input: ``{"asset_ids": ["uuid", ...], "start": "2022-01-01", "end": "2025-12-31", "source": "yfinance"}``
    Output: per-asset session counts, date range, and gap flag.

    Read-only, idempotent. Used by the Data Agent to decide whether a sync
    is needed.
    """

    name = "check_coverage"
    role = "data"
    version = "1.0"
    allowed_callers = frozenset({"data_agent"})
    has_side_effects = False
    idempotent = True
    timeout_seconds = 30

    def execute(self, params: dict[str, Any], *, db: Session) -> ToolResult:
        return run_tool_safely(self.name, self.version, lambda: self._run(params, db))

    def _run(self, params: dict[str, Any], db: Session) -> ToolResult:
        asset_ids_raw = params.get("asset_ids")
        if not isinstance(asset_ids_raw, list) or not asset_ids_raw:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "asset_ids must be a non-empty list"),
            )

        try:
            asset_ids = [uuid.UUID(str(a)) for a in asset_ids_raw]
        except (ValueError, TypeError) as exc:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, f"invalid asset_id: {exc}"),
            )

        start = self._parse_date(params.get("start"))
        end = self._parse_date(params.get("end"))
        if start is None or end is None:
            return ToolResult.fail(
                self.name,
                ToolError.of(
                    ToolErrorKind.VALIDATION, "start and end dates are required (YYYY-MM-DD)"
                ),
            )
        if start > end:
            return ToolResult.fail(
                self.name,
                ToolError.of(ToolErrorKind.VALIDATION, "start must be <= end"),
            )

        source = params.get("source", "yfinance")

        # Query OHLCV counts per asset.
        start_dt = datetime.combine(start, datetime.min.time())
        end_dt = datetime.combine(end, datetime.max.time())

        rows = db.execute(
            select(
                Ohlcv.asset_id,
                func.count().label("sessions"),
                func.min(Ohlcv.time).label("first_bar"),
                func.max(Ohlcv.time).label("last_bar"),
            )
            .where(Ohlcv.asset_id.in_(asset_ids))
            .where(Ohlcv.source == source)
            .where(Ohlcv.time >= start_dt)
            .where(Ohlcv.time <= end_dt)
            .group_by(Ohlcv.asset_id)
        ).all()

        found_ids = {r.asset_id for r in rows}
        coverage: list[dict[str, Any]] = []
        for r in rows:
            coverage.append(
                {
                    "asset_id": str(r.asset_id),
                    "sessions": r.sessions,
                    "first_bar": r.first_bar.isoformat() if r.first_bar else None,
                    "last_bar": r.last_bar.isoformat() if r.last_bar else None,
                }
            )

        missing_ids = [str(a) for a in asset_ids if a not in found_ids]

        return ToolResult.ok(
            self.name,
            {
                "source": source,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "coverage": coverage,
                "missing": missing_ids,
                "gaps_detected": len(missing_ids) > 0,
            },
            tool_version=self.version,
        )

    @staticmethod
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
_register(ResolveAssetsTool())
_register(CheckCoverageTool())
