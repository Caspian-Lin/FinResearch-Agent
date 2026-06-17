"""Real-DB tests for the backtest result ORM models (FRA-26).

Covers the four new tables — ``backtest_runs`` (defaults + config_json
round-trip + nullable benchmark), ``backtest_metrics`` (1:1 with runs,
gross/net sets, PK uniqueness), ``equity_curve`` (hypertable multi-point
insert), and ``trades`` (default cost) — plus the Pydantic read schemas.

Mirrors ``test_ohlcv_ingestion.py``: the host Postgres is used directly, with
surgical cleanup scoped to the ``FRA26TEST`` prefix so nothing else is touched.
``tests/conftest.py`` is left untouched to avoid merge conflicts with parallel
work.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.backtest import (
    BacktestMetrics,
    BacktestRun,
    EquityCurvePoint,
    Trade,
)
from app.models.user import User
from app.schemas.backtest import BacktestRunRead
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

PREFIX = "FRA26TEST"


# ---------------------------------------------------------------------------
# DB helpers + fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    """Delete only rows owned by this suite, respecting FK order."""
    runs = "SELECT id FROM backtest_runs WHERE name LIKE :p"
    db.execute(text(f"DELETE FROM trades WHERE backtest_run_id IN ({runs})"), {"p": f"{PREFIX}%"})
    db.execute(
        text(f"DELETE FROM equity_curve WHERE backtest_run_id IN ({runs})"), {"p": f"{PREFIX}%"}
    )
    db.execute(
        text(f"DELETE FROM backtest_metrics WHERE backtest_run_id IN ({runs})"),
        {"p": f"{PREFIX}%"},
    )
    db.execute(text("DELETE FROM backtest_runs WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
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


def _make_user(db: Session, suffix: str) -> User:
    user = User(email=f"{PREFIX}-{suffix}@test", hashed_password="x", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_asset(db: Session, symbol: str) -> Asset:
    asset = Asset(
        symbol=symbol,
        name=f"Test {symbol}",
        exchange="NASDAQ",
        asset_type="stock",
        currency="USD",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _make_run(
    db: Session, user: User, asset: Asset | None = None, name: str = "FRA26TEST-run"
) -> BacktestRun:
    run = BacktestRun(
        user_id=user.id,
        name=name,
        strategy_type="equal_weight",
        config_json={
            "universe": [str(asset.id)] if asset else [],
            "strategy_name": "equal_weight",
            "initial_capital": 100000.0,
            "cost_bps": 5.0,
            "rebalance": "daily",
            "price_field": "adjusted",
            "benchmark": str(asset.id) if asset else None,
        },
        benchmark_asset_id=asset.id if asset else None,
        start_date=date(2022, 1, 1),
        end_date=date(2023, 1, 1),
        price_field="adjusted",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# ---------------------------------------------------------------------------
# backtest_runs: defaults, config_json round-trip, nullable benchmark
# ---------------------------------------------------------------------------


def test_backtest_run_defaults_and_config_roundtrip(db_session: Session) -> None:
    user = _make_user(db_session, "U1")
    asset = _make_asset(db_session, "FRA26TEST-A")
    config = {
        "universe": [str(asset.id)],
        "strategy_name": "equal_weight",
        "initial_capital": 100000.0,
        "cost_bps": 5.0,
        "rebalance": "daily",
        "price_field": "adjusted",
        "benchmark": str(asset.id),
    }
    run = BacktestRun(
        user_id=user.id,
        name="FRA26TEST-run1",
        strategy_type="equal_weight",
        config_json=config,
        benchmark_asset_id=asset.id,
        start_date=date(2022, 1, 1),
        end_date=date(2023, 1, 1),
        price_field="adjusted",
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    assert run.id is not None
    assert run.status == "pending"  # server + model default
    assert run.created_at is not None
    assert run.config_json == config  # JSONB round-trips a nested dict unchanged

    # benchmark is genuinely nullable
    run2 = BacktestRun(
        user_id=user.id,
        name="FRA26TEST-run2",
        strategy_type="buy_hold",
        config_json={"universe": []},
        start_date=date(2022, 1, 1),
        end_date=date(2023, 1, 1),
        price_field="raw",
    )
    db_session.add(run2)
    db_session.commit()
    db_session.refresh(run2)
    assert run2.benchmark_asset_id is None
    assert run2.price_field == "raw"


# ---------------------------------------------------------------------------
# backtest_metrics: 1:1 with runs, gross/net sets, PK uniqueness
# ---------------------------------------------------------------------------


def test_backtest_metrics_one_to_one_and_uniqueness(db_session: Session) -> None:
    user = _make_user(db_session, "U2")
    run = _make_run(db_session, user)
    metrics = BacktestMetrics(
        backtest_run_id=run.id,
        gross_annual_return=Decimal("0.15"),
        gross_volatility=Decimal("0.20"),
        gross_sharpe_ratio=Decimal("0.75"),
        gross_max_drawdown=Decimal("0.10"),
        gross_calmar_ratio=Decimal("1.5"),
        gross_turnover=Decimal("0.30"),
        gross_win_rate=Decimal("0.55"),
        gross_beta=Decimal("1.05"),
        gross_correlation=Decimal("0.92"),
        net_annual_return=Decimal("0.13"),
        net_volatility=Decimal("0.20"),
        net_sharpe_ratio=Decimal("0.65"),
        net_max_drawdown=Decimal("0.10"),
        net_calmar_ratio=Decimal("1.3"),
        net_turnover=Decimal("0.30"),
        net_win_rate=Decimal("0.55"),
        net_beta=Decimal("1.05"),
        net_correlation=Decimal("0.92"),
    )
    db_session.add(metrics)
    db_session.commit()

    got = db_session.get(BacktestMetrics, run.id)
    assert got is not None
    assert got.gross_sharpe_ratio == Decimal("0.75")
    assert got.net_sharpe_ratio == Decimal("0.65")  # distinct from gross

    # 1:1 — a second metrics row for the same run violates the PK. Use a core
    # insert so the duplicate bypasses the session identity map (an ORM add
    # would raise a noisy SAWarning before the IntegrityError).
    with pytest.raises(IntegrityError):
        db_session.execute(
            insert(BacktestMetrics).values(backtest_run_id=run.id, gross_sharpe_ratio=Decimal("9"))
        )
        db_session.commit()
    db_session.rollback()


# ---------------------------------------------------------------------------
# equity_curve: hypertable multi-point insert
# ---------------------------------------------------------------------------


def test_equity_curve_points(db_session: Session) -> None:
    user = _make_user(db_session, "U3")
    run = _make_run(db_session, user)
    days = [
        datetime(2022, 1, 3, tzinfo=UTC),
        datetime(2022, 1, 4, tzinfo=UTC),
        datetime(2022, 1, 5, tzinfo=UTC),
    ]
    for i, day in enumerate(days):
        db_session.add(
            EquityCurvePoint(
                backtest_run_id=run.id,
                time=day,
                equity=Decimal(100000 + i * 100),
                daily_return=Decimal("0.01") if i else None,
                drawdown=Decimal("-0.02"),
            )
        )
    db_session.commit()

    rows = db_session.scalars(
        select(EquityCurvePoint)
        .where(EquityCurvePoint.backtest_run_id == run.id)
        .order_by(EquityCurvePoint.time)
    ).all()
    assert len(rows) == 3
    assert rows[0].equity == Decimal("100000")
    assert rows[0].daily_return is None  # first day has no prior return
    assert rows[2].equity == Decimal("100200")
    assert all(r.series_kind == "strategy" for r in rows)  # default (FRA-41)


def test_equity_curve_strategy_and_benchmark_coexist(db_session: Session) -> None:
    """三列 PK (run_id, series_kind, time):同 run 同时刻并存 strategy + benchmark(FRA-41)。"""
    user = _make_user(db_session, "U6")
    run = _make_run(db_session, user, name="FRA26TEST-coexist")
    day = datetime(2022, 1, 3, tzinfo=UTC)
    for kind in ("strategy", "benchmark"):
        db_session.add(
            EquityCurvePoint(
                backtest_run_id=run.id,
                series_kind=kind,
                time=day,
                equity=Decimal("100000"),
                daily_return=Decimal("0.01"),
                drawdown=Decimal("0"),
            )
        )
    db_session.commit()

    rows = db_session.scalars(
        select(EquityCurvePoint).where(EquityCurvePoint.backtest_run_id == run.id)
    ).all()
    assert len(rows) == 2  # 不冲突:series_kind 区分
    assert {r.series_kind for r in rows} == {"strategy", "benchmark"}

    # 按 series_kind 过滤查 benchmark 曲线。
    bench = db_session.scalars(
        select(EquityCurvePoint).where(
            EquityCurvePoint.backtest_run_id == run.id,
            EquityCurvePoint.series_kind == "benchmark",
        )
    ).all()
    assert len(bench) == 1


# ---------------------------------------------------------------------------
# trades: default cost, side/quantity/price persisted
# ---------------------------------------------------------------------------


def test_trade_default_cost(db_session: Session) -> None:
    user = _make_user(db_session, "U4")
    asset = _make_asset(db_session, "FRA26TEST-T")
    run = _make_run(db_session, user)
    trade = Trade(
        backtest_run_id=run.id,
        time=datetime(2022, 1, 3, tzinfo=UTC),
        asset_id=asset.id,
        side="buy",
        quantity=Decimal("10"),
        price=Decimal("100.5"),
    )
    db_session.add(trade)
    db_session.commit()
    db_session.refresh(trade)

    assert trade.cost == Decimal("0")  # server + model default
    assert trade.side == "buy"
    assert trade.quantity == Decimal("10")
    assert trade.price == Decimal("100.5")


# ---------------------------------------------------------------------------
# Pydantic read schema round-trips an ORM row via from_attributes
# ---------------------------------------------------------------------------


def test_schema_roundtrip_from_attributes(db_session: Session) -> None:
    user = _make_user(db_session, "U5")
    asset = _make_asset(db_session, "FRA26TEST-S")
    run = _make_run(db_session, user, asset=asset, name="FRA26TEST-schema")

    read = BacktestRunRead.model_validate(run)
    assert read.id == run.id
    assert read.user_id == user.id
    assert read.status == "pending"
    assert read.price_field == "adjusted"
    assert read.benchmark_asset_id == asset.id
    assert read.config_json["strategy_name"] == "equal_weight"
    assert read.start_date == date(2022, 1, 1)
