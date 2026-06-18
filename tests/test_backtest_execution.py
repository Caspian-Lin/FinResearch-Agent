"""Backtest execution integration tests (FRA-37) — real DB.

验证 ``execute_backtest_run`` 端到端:seed asset + ohlcv → create run → 执行 →
metrics + equity_curve 入库 + status success。失败路径(策略未知 / 数据不足)→
status failed + error_message。

模仿 ``test_backtest_models.py`` 的 real-DB + PREFIX 清理范式。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.backtest import BacktestMetrics, BacktestRun, EquityCurvePoint, Trade
from app.models.ohlcv import Ohlcv
from app.models.user import User
from app.services.backtest.execution import execute_backtest_run
from sqlalchemy import select, text
from sqlalchemy.orm import Session

PREFIX = "FRA37TEST"


# ---------------------------------------------------------------------------
# DB helpers + fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    """Delete only this suite's rows, respecting FK order."""
    runs = "SELECT id FROM backtest_runs WHERE name LIKE :p"
    db.execute(
        text(f"DELETE FROM equity_curve WHERE backtest_run_id IN ({runs})"), {"p": f"{PREFIX}%"}
    )
    db.execute(
        text(f"DELETE FROM backtest_metrics WHERE backtest_run_id IN ({runs})"), {"p": f"{PREFIX}%"}
    )
    db.execute(text(f"DELETE FROM trades WHERE backtest_run_id IN ({runs})"), {"p": f"{PREFIX}%"})
    db.execute(text("DELETE FROM backtest_runs WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
    db.execute(
        text(
            "DELETE FROM ohlcv WHERE source='yfinance' AND asset_id IN "
            "(SELECT id FROM assets WHERE symbol LIKE :p)"
        ),
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


def _utc(day: str) -> datetime:
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, tzinfo=UTC)


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


def _seed_ohlcv(db: Session, asset: Asset, day_prices: list[tuple[str, float]]) -> None:
    for day, price in day_prices:
        db.add(
            Ohlcv(
                asset_id=asset.id,
                time=_utc(day),
                source="yfinance",
                close=Decimal(str(price)),
                adjusted_close=Decimal(str(price)),
            )
        )
    db.commit()


def _make_run(db: Session, user: User, asset: Asset, **cfg_overrides: object) -> BacktestRun:
    cfg: dict[str, object] = {
        "universe": [str(asset.id)],
        "strategy_name": "buy_hold",
        "initial_capital": 100000.0,
        "cost_bps": 0.0,
        "rebalance": "daily",
        "price_field": "adjusted",
    }
    cfg.update(cfg_overrides)
    run = BacktestRun(
        user_id=user.id,
        name=f"{PREFIX}-run",
        strategy_type=str(cfg["strategy_name"]),
        config_json=cfg,
        benchmark_asset_id=None,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 5),
        price_field="adjusted",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# ---------------------------------------------------------------------------
# happy path — persisted metrics + equity_curve + status success
# ---------------------------------------------------------------------------


def test_execute_success_persists_metrics_and_curve(db_session: Session) -> None:
    user = _make_user(db_session, "U1")
    asset = _make_asset(db_session, f"{PREFIX}-A")
    _seed_ohlcv(
        db_session,
        asset,
        [
            ("2024-01-02", 100.0),
            ("2024-01-03", 101.0),
            ("2024-01-04", 103.0),
            ("2024-01-05", 102.0),
        ],
    )
    run = _make_run(db_session, user, asset)

    result = execute_backtest_run(str(run.id))

    assert result["status"] == "success"
    assert result["equity_points"] == 4
    db_session.refresh(run)
    assert run.status == "success"
    assert run.error_message is None

    # metrics 1:1 入库。
    metrics = db_session.get(BacktestMetrics, run.id)
    assert metrics is not None
    assert metrics.gross_annual_return is not None
    assert metrics.net_annual_return is not None

    # equity_curve strategy 行(4 交易日)。
    pts = db_session.scalars(
        select(EquityCurvePoint).where(EquityCurvePoint.backtest_run_id == run.id)
    ).all()
    assert len(pts) == 4
    assert all(p.series_kind == "strategy" for p in pts)


# ---------------------------------------------------------------------------
# failure paths — status failed + error_message recorded
# ---------------------------------------------------------------------------


def test_execute_unknown_strategy_marks_failed(db_session: Session) -> None:
    user = _make_user(db_session, "U2")
    asset = _make_asset(db_session, f"{PREFIX}-B")
    _seed_ohlcv(db_session, asset, [("2024-01-02", 100.0)])
    run = _make_run(db_session, user, asset, strategy_name="nonexistent")

    with pytest.raises(ValueError, match="unknown strategy"):
        execute_backtest_run(str(run.id))

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_message is not None
    assert "unknown strategy" in run.error_message


def test_execute_missing_prices_marks_failed(db_session: Session) -> None:
    user = _make_user(db_session, "U3")
    asset = _make_asset(db_session, f"{PREFIX}-C")
    # asset 存在但无 ohlcv 数据 → load_prices raise
    run = _make_run(db_session, user, asset)

    with pytest.raises(ValueError, match="no usable price data"):
        execute_backtest_run(str(run.id))

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_message is not None


# ---------------------------------------------------------------------------
# trades 入库(FRA-42)
# ---------------------------------------------------------------------------


def test_execute_persists_trades(db_session: Session) -> None:
    user = _make_user(db_session, "U4")
    asset = _make_asset(db_session, f"{PREFIX}-D")
    _seed_ohlcv(
        db_session,
        asset,
        [
            ("2024-01-02", 100.0),
            ("2024-01-03", 101.0),
            ("2024-01-04", 103.0),
            ("2024-01-05", 102.0),
        ],
    )
    run = _make_run(db_session, user, asset, strategy_name="buy_hold")

    result = execute_backtest_run(str(run.id))

    assert result["status"] == "success"
    trades = list(db_session.scalars(select(Trade).where(Trade.backtest_run_id == run.id)).all())
    # buy_hold 单资产:首日建仓 0→1.0 产生 ≥1 笔 buy trade(price/quantity/cost 已定量化)。
    assert len(trades) >= 1
    t = trades[0]
    assert t.side == "buy"
    assert t.asset_id == asset.id
    assert float(t.quantity) > 0
    assert float(t.price) > 0
