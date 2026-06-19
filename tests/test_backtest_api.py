"""Backtest API tests (FRA-36) — TestClient + mock queue, real DB session.

POST /backtest 用 mock queue(不真 enqueue worker;worker 端到端在
test_backtest_execution 覆盖);GET/list 用真实 DB seed 验证 ownership + 结果聚合。
模仿 ``test_watchlists_api.py`` 的 client/register/asset 范式。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.asset import Asset
from app.models.backtest import BacktestMetrics, BacktestRun, EquityCurvePoint, Trade
from app.services.sync import get_backtest_queue
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

PREFIX = "FRA36TEST"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    runs = "SELECT id FROM backtest_runs WHERE name LIKE :p"
    db.execute(
        text(f"DELETE FROM equity_curve WHERE backtest_run_id IN ({runs})"), {"p": f"{PREFIX}%"}
    )
    db.execute(
        text(f"DELETE FROM backtest_metrics WHERE backtest_run_id IN ({runs})"), {"p": f"{PREFIX}%"}
    )
    db.execute(text(f"DELETE FROM trades WHERE backtest_run_id IN ({runs})"), {"p": f"{PREFIX}%"})
    db.execute(text("DELETE FROM backtest_runs WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
    db.execute(text("DELETE FROM assets WHERE symbol LIKE :p"), {"p": f"{PREFIX}%"})
    db.execute(text("DELETE FROM users WHERE email ILIKE :p"), {"p": f"{PREFIX}%"})
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


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    # mock queue:POST 只验 run 创建 + enqueue 调用,不真跑 worker。
    app.dependency_overrides[get_backtest_queue] = lambda: MagicMock()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _register(client: TestClient, suffix: str) -> tuple[str, uuid.UUID]:
    """Register + login; return (access_token, user_id)。"""
    email = f"{PREFIX}-{suffix}@example.com"
    reg = client.post("/auth/register", json={"email": email, "password": "supersecretpw"})
    assert reg.status_code == 201, reg.text
    r = client.post("/auth/login", json={"email": email, "password": "supersecretpw"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"], uuid.UUID(reg.json()["id"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def _payload(name: str, asset_id: uuid.UUID, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "strategy_name": "buy_hold",
        "universe": [str(asset_id)],
        "start": "2024-01-02",
        "end": "2024-01-31",
    }
    payload.update(overrides)
    return payload


def _seed_finished_run(db: Session, user_id: uuid.UUID, tag: str) -> BacktestRun:
    """直接在 DB 建一个 success run + metrics + 1 个 strategy 曲线点。"""
    run = BacktestRun(
        user_id=user_id,
        name=f"{PREFIX}-run-{tag}",
        strategy_type="buy_hold",
        config_json={"strategy_name": "buy_hold", "universe": []},
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 5),
        price_field="adjusted",
        status="success",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    db.add(
        BacktestMetrics(
            backtest_run_id=run.id,
            gross_annual_return=Decimal("0.15"),
            net_annual_return=Decimal("0.13"),
        )
    )
    db.add(
        EquityCurvePoint(
            backtest_run_id=run.id,
            series_kind="strategy",
            time=datetime(2024, 1, 2, tzinfo=UTC),
            equity=Decimal("100000"),
        )
    )
    db.commit()
    return run


# ---------------------------------------------------------------------------
# POST /backtest — create + enqueue
# ---------------------------------------------------------------------------


def test_create_backtest_enqueues_run(client: TestClient, db_session: Session) -> None:
    token, _ = _register(client, "U1")
    asset = _make_asset(db_session, f"{PREFIX}-A")

    r = client.post("/backtest", json=_payload(f"{PREFIX}-run1", asset.id), headers=_auth(token))

    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"
    run_id = uuid.UUID(body["run_id"])

    run = db_session.get(BacktestRun, run_id)
    assert run is not None
    assert run.status == "pending"
    assert run.strategy_type == "buy_hold"
    assert run.config_json["universe"] == [str(asset.id)]


def test_create_backtest_config_snapshot_contains_reproducibility_fields(
    client: TestClient, db_session: Session
) -> None:
    token, _ = _register(client, "U1B")
    asset = _make_asset(db_session, f"{PREFIX}-SNAP")
    benchmark = _make_asset(db_session, f"{PREFIX}-QQQ")

    r = client.post(
        "/backtest",
        json=_payload(
            f"{PREFIX}-snapshot",
            asset.id,
            start="2024-01-02",
            end="2024-03-29",
            benchmark_asset_id=str(benchmark.id),
            strategy_name="ma_crossover",
            initial_capital=250000.0,
            cost_bps=7.5,
            rebalance="weekly",
            price_field="raw",
            strategy_params={"fast": 5, "slow": 20},
        ),
        headers=_auth(token),
    )

    assert r.status_code == 202
    run = db_session.get(BacktestRun, uuid.UUID(r.json()["run_id"]))
    assert run is not None
    assert run.config_json == {
        "universe": [str(asset.id)],
        "start": "2024-01-02",
        "end": "2024-03-29",
        "strategy_name": "ma_crossover",
        "initial_capital": 250000.0,
        "cost_bps": 7.5,
        "rebalance": "weekly",
        "price_field": "raw",
        "benchmark": str(benchmark.id),
        "strategy_params": {"fast": 5, "slow": 20},
    }


def test_create_backtest_unknown_asset_404(client: TestClient, db_session: Session) -> None:
    token, _ = _register(client, "U2")
    r = client.post(
        "/backtest",
        json=_payload(f"{PREFIX}-run2", uuid.uuid4()),  # 不存在的 asset
        headers=_auth(token),
    )
    assert r.status_code == 404


def test_create_backtest_bad_strategy_422(client: TestClient, db_session: Session) -> None:
    token, _ = _register(client, "U3")
    asset = _make_asset(db_session, f"{PREFIX}-B")
    r = client.post(
        "/backtest",
        json=_payload(f"{PREFIX}-run3", asset.id, strategy_name="bogus"),
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_create_backtest_unauth_401(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, f"{PREFIX}-D")
    r = client.post("/backtest", json=_payload(f"{PREFIX}-run4", asset.id))
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /backtest/{run_id} — detail + ownership
# ---------------------------------------------------------------------------


def test_get_backtest_returns_detail(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U5")
    run = _seed_finished_run(db_session, user_id, "d1")

    r = client.get(f"/backtest/{run.id}", headers=_auth(token))

    assert r.status_code == 200
    body = r.json()
    assert body["run"]["id"] == str(run.id)
    assert body["run"]["status"] == "success"
    # Decimal → float 序列化(FRA-24 模式):数值字段为 JSON number,非 string。
    assert body["metrics"]["gross_annual_return"] == 0.15
    assert len(body["equity_curve"]) == 1
    assert body["equity_curve"][0]["series_kind"] == "strategy"


def test_get_backtest_other_user_404(client: TestClient, db_session: Session) -> None:
    _, owner_id = _register(client, "U6")  # 拥有者
    other_token, _ = _register(client, "U7")  # 他人
    run = _seed_finished_run(db_session, owner_id, "d2")

    r = client.get(f"/backtest/{run.id}", headers=_auth(other_token))
    assert r.status_code == 404  # ownership:他人 run 不可见


def test_get_backtest_missing_404(client: TestClient, db_session: Session) -> None:
    token, _ = _register(client, "U8")
    r = client.get(f"/backtest/{uuid.uuid4()}", headers=_auth(token))
    assert r.status_code == 404


def test_get_backtest_returns_trades(client: TestClient, db_session: Session) -> None:
    """detail 响应含 trades(FRA-38:交易明细可查;复现 FRA-42 入库形态)。"""
    token, user_id = _register(client, "U13")
    asset = _make_asset(db_session, f"{PREFIX}-TR")
    run = _seed_finished_run(db_session, user_id, "tr1")
    # 直接 seed 1 笔 buy trade(复现 FRA-42 入库形态:quantity/price/cost)。
    db_session.add(
        Trade(
            backtest_run_id=run.id,
            time=datetime(2024, 1, 2, tzinfo=UTC),
            asset_id=asset.id,
            side="buy",
            quantity=Decimal("100"),
            price=Decimal("100.00"),
            cost=Decimal("1.00"),
        )
    )
    db_session.commit()

    r = client.get(f"/backtest/{run.id}", headers=_auth(token))

    assert r.status_code == 200
    body = r.json()
    assert len(body["trades"]) == 1
    t = body["trades"][0]
    assert t["side"] == "buy"
    assert t["asset_id"] == str(asset.id)
    # Decimal → float 序列化(FRA-24 模式)。
    assert t["quantity"] == 100.0
    assert t["price"] == 100.0


# ---------------------------------------------------------------------------
# GET /backtest — list + pagination
# ---------------------------------------------------------------------------


def test_list_backtests_own_only(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U9")
    _seed_finished_run(db_session, user_id, "L1")
    _seed_finished_run(db_session, user_id, "L2")
    _register(client, "U10")  # 他人(无 run)

    r = client.get("/backtest", headers=_auth(token))

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert all(item["status"] == "success" for item in body["items"])


def test_list_backtests_pagination(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U11")
    for i in range(3):
        _seed_finished_run(db_session, user_id, f"P{i}")

    r = client.get("/backtest?limit=2&offset=0", headers=_auth(token))
    assert r.json()["total"] == 3
    assert len(r.json()["items"]) == 2

    r2 = client.get("/backtest?limit=2&offset=2", headers=_auth(token))
    assert len(r2.json()["items"]) == 1


# ---------------------------------------------------------------------------
# sanity: ownership scoping uses the count query path too
# ---------------------------------------------------------------------------


def test_list_backtests_empty_for_new_user(client: TestClient, db_session: Session) -> None:
    token, _ = _register(client, "U12")
    r = client.get("/backtest", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []
