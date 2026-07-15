"""Tests for the agent tool registry (FRA-87).

Covers:
* Registry: get_tool, validate_caller, unknown tool, wrong role.
* ResolveAssetsTool: found, not-found, ambiguous, validation.
* CheckCoverageTool: coverage check, gaps, validation.
* ComputeFactorTool: allowlist rejection, validation.
* EvaluateFactorTool: allowlist rejection, insufficient data.
* RunBacktestTool: strategy/rebalance validation, not-idempotent.
* ReadBacktestTool: found, not-found.
* run_tool_safely: exception classification.

DB tests use surgical FRA87TEST-prefixed cleanup. No test accesses the network.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.backtest import BacktestRun
from app.models.ohlcv import Ohlcv
from app.models.user import User
from app.services.agent.tools import (
    TOOL_REGISTRY,
    ToolError,
    ToolErrorKind,
    ToolResult,
    get_tool,
    validate_caller,
)
from app.services.agent.tools.protocol import _classify_exception, run_tool_safely
from sqlalchemy import text
from sqlalchemy.orm import Session

PREFIX = "FRA87TEST"


# ─── DB helpers ──────────────────────────────────────────────────────────────


def _cleanup(db: Session) -> None:
    db.execute(
        text(
            "DELETE FROM equity_curve WHERE backtest_run_id IN (SELECT id FROM backtest_runs WHERE name LIKE :p)"
        ),
        {"p": f"{PREFIX}%"},
    )
    db.execute(
        text(
            "DELETE FROM trades WHERE backtest_run_id IN (SELECT id FROM backtest_runs WHERE name LIKE :p)"
        ),
        {"p": f"{PREFIX}%"},
    )
    db.execute(
        text(
            "DELETE FROM backtest_metrics WHERE backtest_run_id IN (SELECT id FROM backtest_runs WHERE name LIKE :p)"
        ),
        {"p": f"{PREFIX}%"},
    )
    db.execute(text("DELETE FROM backtest_runs WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
    db.execute(
        text(
            "DELETE FROM factor_values WHERE asset_id IN (SELECT id FROM assets WHERE symbol LIKE :p)"
        ),
        {"p": f"{PREFIX}%"},
    )
    db.execute(
        text("DELETE FROM ohlcv WHERE asset_id IN (SELECT id FROM assets WHERE symbol LIKE :p)"),
        {"p": f"{PREFIX}%"},
    )
    db.execute(text("DELETE FROM assets WHERE symbol LIKE :p"), {"p": f"{PREFIX}%"})
    db.execute(text("DELETE FROM users WHERE email LIKE :p"), {"p": f"{PREFIX}%"})
    db.commit()


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)
        db.close()


def _make_user(db: Session) -> User:
    user = User(email=f"{PREFIX}@test.com", hashed_password="x", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_asset(
    db: Session, symbol: str, *, exchange: str = "NASDAQ", data_source: str = "yfinance"
) -> Asset:
    asset = Asset(
        symbol=symbol,
        name=f"{PREFIX} {symbol}",
        exchange=exchange,
        asset_type="stock",
        data_source=data_source,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _seed_ohlcv(
    db: Session,
    asset: Asset,
    *,
    start: date = date(2022, 6, 1),
    days: int = 30,
    source: str = "yfinance",
) -> int:
    """Insert *days* of OHLCV bars ending at *start* + days."""
    bars: list[Ohlcv] = []
    for i in range(days):
        dt = datetime.combine(start + timedelta(days=i), datetime.min.time(), tzinfo=UTC)
        price = Decimal("100") + Decimal(str(i))
        bars.append(
            Ohlcv(
                asset_id=asset.id,
                time=dt,
                source=source,
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                adjusted_close=price,
                volume=1_000_000,
            )
        )
    db.bulk_save_objects(bars)
    db.commit()
    return len(bars)


# ─── Registry tests ──────────────────────────────────────────────────────────


def test_registry_has_all_expected_tools() -> None:
    expected = {
        "resolve_assets",
        "check_coverage",
        "compute_factor",
        "evaluate_factor",
        "run_backtest",
        "read_backtest",
    }
    assert expected <= set(TOOL_REGISTRY)


def test_get_tool_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        get_tool("nonsense")


def test_validate_caller_happy_path() -> None:
    validate_caller("resolve_assets", "data_agent")
    validate_caller("resolve_assets", "research_planner")
    validate_caller("compute_factor", "factor_agent")
    validate_caller("run_backtest", "backtest_agent")


def test_validate_caller_wrong_role() -> None:
    with pytest.raises(ValueError, match="not permitted"):
        validate_caller("run_backtest", "data_agent")


def test_validate_caller_unknown_role() -> None:
    with pytest.raises(ValueError, match="unknown agent role"):
        validate_caller("resolve_assets", "bogus_role")


def test_tool_metadata_consistency() -> None:
    for name, tool in TOOL_REGISTRY.items():
        assert tool.name == name
        assert tool.version
        assert tool.role in {"data", "factor", "backtest", "risk", "report"}
        assert isinstance(tool.allowed_callers, frozenset)
        assert isinstance(tool.has_side_effects, bool)
        assert isinstance(tool.idempotent, bool)
        assert tool.timeout_seconds >= 1


# ─── ResolveAssetsTool ───────────────────────────────────────────────────────


def test_resolve_assets_found(db_session: Session) -> None:
    asset = _make_asset(db_session, f"{PREFIX}-AAPL")
    tool = get_tool("resolve_assets")
    result = tool.execute({"symbols": [f"{PREFIX}-AAPL"]}, db=db_session)

    assert result.success
    assert result.data is not None
    assert result.data["count"] == 1
    entry = result.data["resolved"][0]
    assert entry["asset_id"] == str(asset.id)
    assert entry["data_source"] == "yfinance"


def test_resolve_assets_not_found(db_session: Session) -> None:
    tool = get_tool("resolve_assets")
    result = tool.execute({"symbols": ["NONEXIST"]}, db=db_session)

    assert result.success  # resolving is not an error
    assert result.data is not None
    assert result.data["unresolved"] == ["NONEXIST"]
    assert result.data["resolved"] == []


def test_resolve_assets_ambiguous(db_session: Session) -> None:
    sym = f"{PREFIX}-DUAL"
    _make_asset(db_session, sym, exchange="NASDAQ")
    _make_asset(db_session, sym, exchange="NYSE")
    tool = get_tool("resolve_assets")
    result = tool.execute({"symbols": [sym]}, db=db_session)

    assert result.success
    assert result.data is not None
    assert result.data["ambiguous"]
    assert set(result.data["ambiguous"][0]["exchanges"]) == {"NASDAQ", "NYSE"}


def test_resolve_assets_validation_empty(db_session: Session) -> None:
    tool = get_tool("resolve_assets")
    result = tool.execute({"symbols": []}, db=db_session)
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.VALIDATION


# ─── CheckCoverageTool ───────────────────────────────────────────────────────


def test_check_coverage_with_data(db_session: Session) -> None:
    asset = _make_asset(db_session, f"{PREFIX}-P")
    n = _seed_ohlcv(db_session, asset, days=20)
    tool = get_tool("check_coverage")
    result = tool.execute(
        {
            "asset_ids": [str(asset.id)],
            "start": "2022-06-01",
            "end": "2022-12-31",
            "source": "yfinance",
        },
        db=db_session,
    )

    assert result.success
    assert result.data is not None
    cov = result.data["coverage"][0]
    assert cov["sessions"] == n
    assert result.data["missing"] == []


def test_check_coverage_gaps(db_session: Session) -> None:
    asset = _make_asset(db_session, f"{PREFIX}-GAP")
    _seed_ohlcv(db_session, asset, days=5)
    tool = get_tool("check_coverage")
    result = tool.execute(
        {
            "asset_ids": [str(asset.id), str(uuid.uuid4())],  # second is missing
            "start": "2022-06-01",
            "end": "2022-06-30",
        },
        db=db_session,
    )

    assert result.success
    assert result.data is not None
    assert result.data["gaps_detected"] is True
    assert len(result.data["missing"]) == 1


def test_check_coverage_validation_bad_date(db_session: Session) -> None:
    asset = _make_asset(db_session, f"{PREFIX}-V")
    tool = get_tool("check_coverage")
    result = tool.execute(
        {"asset_ids": [str(asset.id)], "start": "not-a-date", "end": "2022-01-01"},
        db=db_session,
    )
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.VALIDATION


# ─── ComputeFactorTool validation ────────────────────────────────────────────


def test_compute_factor_unknown_factor(db_session: Session) -> None:
    asset = _make_asset(db_session, f"{PREFIX}-F")
    tool = get_tool("compute_factor")
    result = tool.execute(
        {
            "asset_ids": [str(asset.id)],
            "factor_names": ["bogus_factor"],
            "start": "2022-01-01",
            "end": "2023-01-01",
        },
        db=db_session,
    )
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.VALIDATION
    assert "bogus_factor" in result.error.message


def test_compute_factor_empty_asset_ids(db_session: Session) -> None:
    tool = get_tool("compute_factor")
    result = tool.execute(
        {
            "asset_ids": [],
            "factor_names": ["momentum_21"],
            "start": "2022-01-01",
            "end": "2023-01-01",
        },
        db=db_session,
    )
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.VALIDATION


# ─── EvaluateFactorTool validation ───────────────────────────────────────────


def test_evaluate_factor_unknown_factor(db_session: Session) -> None:
    asset = _make_asset(db_session, f"{PREFIX}-E")
    tool = get_tool("evaluate_factor")
    result = tool.execute(
        {
            "asset_ids": [str(asset.id)],
            "factor_name": "bogus",
            "start": "2022-01-01",
            "end": "2023-01-01",
        },
        db=db_session,
    )
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.VALIDATION


def test_evaluate_factor_no_data(db_session: Session) -> None:
    asset = _make_asset(db_session, f"{PREFIX}-ND")
    tool = get_tool("evaluate_factor")
    result = tool.execute(
        {
            "asset_ids": [str(asset.id)],
            "factor_name": "momentum_21",
            "start": "2022-01-01",
            "end": "2023-01-01",
        },
        db=db_session,
    )
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.INSUFFICIENT_DATA


# ─── RunBacktestTool validation ──────────────────────────────────────────────


def test_run_backtest_unknown_strategy(db_session: Session) -> None:
    asset = _make_asset(db_session, f"{PREFIX}-B")
    tool = get_tool("run_backtest")
    result = tool.execute(
        {
            "universe": [str(asset.id)],
            "strategy_name": "bogus_strategy",
            "start": "2022-01-01",
            "end": "2023-01-01",
        },
        db=db_session,
    )
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.VALIDATION


def test_run_backtest_bad_rebalance(db_session: Session) -> None:
    asset = _make_asset(db_session, f"{PREFIX}-BR")
    tool = get_tool("run_backtest")
    result = tool.execute(
        {
            "universe": [str(asset.id)],
            "strategy_name": "momentum",
            "rebalance": "quarterly",
            "start": "2022-01-01",
            "end": "2023-01-01",
        },
        db=db_session,
    )
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.VALIDATION


def test_run_backtest_start_after_end(db_session: Session) -> None:
    asset = _make_asset(db_session, f"{PREFIX}-SE")
    tool = get_tool("run_backtest")
    result = tool.execute(
        {
            "universe": [str(asset.id)],
            "strategy_name": "momentum",
            "start": "2023-01-01",
            "end": "2022-01-01",
        },
        db=db_session,
    )
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.VALIDATION


def test_run_backtest_empty_universe(db_session: Session) -> None:
    tool = get_tool("run_backtest")
    result = tool.execute(
        {"universe": [], "strategy_name": "buy_hold", "start": "2022-01-01", "end": "2023-01-01"},
        db=db_session,
    )
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.VALIDATION


# ─── ReadBacktestTool ────────────────────────────────────────────────────────


def test_read_backtest_not_found(db_session: Session) -> None:
    tool = get_tool("read_backtest")
    result = tool.execute({"run_id": str(uuid.uuid4())}, db=db_session)
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.NOT_FOUND


def test_read_backtest_found(db_session: Session) -> None:
    user = _make_user(db_session)
    asset = _make_asset(db_session, f"{PREFIX}-RB")
    run = BacktestRun(
        user_id=user.id,
        name=f"{PREFIX}-run",
        strategy_type="buy_hold",
        config_json={"universe": [str(asset.id)]},
        start_date=date(2022, 1, 1),
        end_date=date(2023, 1, 1),
        price_field="adjusted",
        status="pending",
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    tool = get_tool("read_backtest")
    result = tool.execute({"run_id": str(run.id)}, db=db_session)
    assert result.success
    assert result.data is not None
    assert result.data["status"] == "pending"
    assert result.data["strategy"] == "buy_hold"


def test_read_backtest_validation_bad_uuid(db_session: Session) -> None:
    tool = get_tool("read_backtest")
    result = tool.execute({"run_id": "not-a-uuid"}, db=db_session)
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.VALIDATION


# ─── run_tool_safely + error classification ─────────────────────────────────


def test_run_tool_safely_catches_exception() -> None:
    def boom() -> ToolResult:
        raise RuntimeError("unexpected boom")

    result = run_tool_safely("test_tool", "1.0", boom)
    assert not result.success
    assert result.error is not None
    assert result.error.kind == ToolErrorKind.INTERNAL
    assert "boom" in result.error.message
    assert result.tool == "test_tool"


def test_classify_exception_not_found() -> None:
    assert _classify_exception(ValueError("asset not found")) == ToolErrorKind.NOT_FOUND
    assert _classify_exception(ValueError("record does not exist")) == ToolErrorKind.NOT_FOUND


def test_classify_exception_insufficient_data() -> None:
    assert (
        _classify_exception(ValueError("insufficient price data"))
        == ToolErrorKind.INSUFFICIENT_DATA
    )


def test_classify_exception_timeout() -> None:
    assert _classify_exception(TimeoutError("operation timed out")) == ToolErrorKind.TIMEOUT


def test_classify_exception_internal_default() -> None:
    assert _classify_exception(RuntimeError("something broke")) == ToolErrorKind.INTERNAL


def test_tool_error_of_truncates_message() -> None:
    long_msg = "x" * 600
    err = ToolError.of(ToolErrorKind.INTERNAL, long_msg)
    assert len(err.message) <= 500


def test_tool_error_of_retriable_auto() -> None:
    assert ToolError.of(ToolErrorKind.PROVIDER, "x").retriable is True
    assert ToolError.of(ToolErrorKind.VALIDATION, "x").retriable is False
    assert ToolError.of(ToolErrorKind.VALIDATION, "x", retriable=True).retriable is True
