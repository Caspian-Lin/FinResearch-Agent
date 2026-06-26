"""Factor worker tests (FRA-57) — execute_* state machine + async API.

两部分:

1. service 层(``execute_factor_*``):real DB,直接调(不依赖 RQ/Redis),验证
   状态机 pending → running → success/failed、``result_json`` 写入、失败原因记录、
   防前视数据不足 → failed。模仿 ``test_backtest_execution.py`` 范式。
2. API 层(``POST /factors/*-async`` + ``GET /factors/jobs/{id}``):TestClient +
   mock queue(同 ``test_backtest_api.py``),验入队 202 + 轮询 + ownership + auth + 校验。

PREFIX 清理覆盖 factor_values / backtest_runs / ohlcv / assets / users。
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
import pytest
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.asset import Asset
from app.models.backtest import BacktestRun
from app.models.factor import FactorValue
from app.services.factors.jobs import (
    execute_factor_compute,
    execute_factor_quantile,
    execute_factor_sweep,
)
from app.services.sync import get_backtest_queue
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

PREFIX = "FRA57TEST"
SRC = "FRA57SRC"


# ---------------------------------------------------------------------------
# DB helpers + fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    owned = "SELECT id FROM assets WHERE symbol LIKE :p"
    users = "SELECT id FROM users WHERE email ILIKE :p"
    db.execute(text(f"DELETE FROM factor_values WHERE asset_id IN ({owned})"), {"p": f"{PREFIX}%"})
    # 按 user_id 删 run(API 异步端点不传 name 时 run 名为 factor_*-{hex},不含 PREFIX,
    # 不能靠 name LIKE;用 user 归属兜底,确保不残留 → 删 user 时 FK 不被违)。
    db.execute(text(f"DELETE FROM backtest_runs WHERE user_id IN ({users})"), {"p": f"{PREFIX}%"})
    db.execute(text(f"DELETE FROM ohlcv WHERE asset_id IN ({owned})"), {"p": f"{PREFIX}%"})
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


def _make_user(db: Session, suffix: str):
    from app.models.user import User

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


def _add_bar(db: Session, asset_id: uuid.UUID, day: date, price: int) -> None:
    from app.models.ohlcv import Ohlcv

    db.add(
        Ohlcv(
            asset_id=asset_id,
            time=datetime(day.year, day.month, day.day, tzinfo=UTC),
            source=SRC,
            open=Decimal(price),
            high=Decimal(price),
            low=Decimal(price),
            close=Decimal(price),
            adjusted_close=Decimal(price),
            volume=1000,
        )
    )


def _seed_universe(db: Session, n: int = 5) -> tuple[list[Asset], date, date]:
    """Seed n assets with distinct drifts over 50 business days; return (assets, start, end)."""
    drifts = [0.003, 0.0015, 0.0, -0.0015, -0.003]
    assets = [_make_asset(db, f"{PREFIX}-{chr(ord('A') + i)}") for i in range(n)]
    days = pd.bdate_range("2023-01-02", periods=50)
    for j, day_ts in enumerate(days):
        day = day_ts.date()
        for asset, drift in zip(assets, drifts, strict=True):
            price = round(100 * ((1 + drift) ** j))
            _add_bar(db, asset.id, day, price)
    db.commit()
    return assets, days[0].date(), days[-1].date()


def _make_run(
    db: Session,
    user,
    *,
    run_kind: str,
    config: dict,
    start: date,
    end: date,
    price_field: str = "adjusted",
    status: str = "pending",
) -> BacktestRun:
    run = BacktestRun(
        user_id=user.id,
        name=f"{PREFIX}-{run_kind}-{uuid.uuid4().hex[:6]}",
        strategy_type="factor",
        config_json=config,
        benchmark_asset_id=None,
        start_date=start,
        end_date=end,
        price_field=price_field,
        status=status,
        run_kind=run_kind,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# ===========================================================================
# service 层:execute_* 状态机
# ===========================================================================


def test_execute_factor_compute_success(db_session: Session) -> None:
    user = _make_user(db_session, "U1")
    assets, start, end = _seed_universe(db_session)
    run = _make_run(
        db_session,
        user,
        run_kind="factor_compute",
        config={
            "universe": [str(a.id) for a in assets],
            "source": SRC,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "price_field": "adjusted",
            "factor_names": ["momentum_21", "rsi_14", "macd_hist"],
        },
        start=start,
        end=end,
    )

    result = execute_factor_compute(str(run.id))

    assert result["status"] == "success"
    assert result["result"]["rows_written"] > 0
    assert set(result["result"]["factor_names"]) == {"momentum_21", "rsi_14", "macd_hist"}
    db_session.refresh(run)
    assert run.status == "success"
    assert run.error_message is None
    assert run.result_json is not None
    assert run.result_json["rows_written"] > 0
    # factor_values 真落库。
    n = db_session.scalar(
        select(func.count()).select_from(FactorValue).where(FactorValue.source == SRC)
    )
    assert n > 0


def test_execute_factor_compute_missing_prices_failed(db_session: Session) -> None:
    user = _make_user(db_session, "U2")
    bare = _make_asset(db_session, f"{PREFIX}-BARE")  # asset 存在但无 ohlcv
    run = _make_run(
        db_session,
        user,
        run_kind="factor_compute",
        config={
            "universe": [str(bare.id)],
            "source": SRC,
            "start": "2023-01-02",
            "end": "2023-02-01",
            "price_field": "adjusted",
            "factor_names": ["momentum_21"],
        },
        start=date(2023, 1, 2),
        end=date(2023, 2, 1),
    )

    with pytest.raises(ValueError):
        execute_factor_compute(str(run.id))

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_message is not None  # 失败可查原因


def test_execute_factor_quantile_success(db_session: Session) -> None:
    user = _make_user(db_session, "U3")
    assets, start, end = _seed_universe(db_session)
    run = _make_run(
        db_session,
        user,
        run_kind="factor_quantile",
        config={
            "universe": [str(a.id) for a in assets],
            "source": SRC,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "price_field": "adjusted",
            "factor_name": "momentum_21",
            "n_quantiles": 5,
        },
        start=start,
        end=end,
    )

    result = execute_factor_quantile(str(run.id))

    assert result["status"] == "success"
    res = result["result"]
    assert set(res["quantile_equity"].keys()) == {"1", "2", "3", "4", "5"}
    assert isinstance(res["top_minus_bottom"], list)
    assert isinstance(res["monotonicity"], float)
    db_session.refresh(run)
    assert run.status == "success"
    assert run.result_json is not None


def test_execute_factor_quantile_macd_hist_success(db_session: Session) -> None:
    user = _make_user(db_session, "U3M")
    assets, start, end = _seed_universe(db_session)
    run = _make_run(
        db_session,
        user,
        run_kind="factor_quantile",
        config={
            "universe": [str(a.id) for a in assets],
            "source": SRC,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "price_field": "adjusted",
            "factor_name": "macd_hist",
            "n_quantiles": 5,
        },
        start=start,
        end=end,
    )

    result = execute_factor_quantile(str(run.id))

    assert result["status"] == "success"
    assert set(result["result"]["quantile_equity"].keys()) == {"1", "2", "3", "4", "5"}
    db_session.refresh(run)
    assert run.status == "success"


def test_execute_factor_quantile_unknown_factor_failed(db_session: Session) -> None:
    user = _make_user(db_session, "U4")
    assets, start, end = _seed_universe(db_session)
    run = _make_run(
        db_session,
        user,
        run_kind="factor_quantile",
        config={
            "universe": [str(a.id) for a in assets],
            "source": SRC,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "price_field": "adjusted",
            "factor_name": "bogus",
            "n_quantiles": 5,
        },
        start=start,
        end=end,
    )

    with pytest.raises(ValueError, match="unknown factor"):
        execute_factor_quantile(str(run.id))

    db_session.refresh(run)
    assert run.status == "failed"
    assert "unknown factor" in (run.error_message or "")


def test_execute_factor_sweep_success(db_session: Session) -> None:
    user = _make_user(db_session, "U5")
    assets, start, end = _seed_universe(db_session)
    run = _make_run(
        db_session,
        user,
        run_kind="factor_sweep",
        config={
            "universe": [str(a.id) for a in assets],
            "source": SRC,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "price_field": "adjusted",
            "factors": ["momentum"],
            "windows": {"momentum": [21]},
            "top_ks": [1, 3],
            "quantiles": [],
            "n_quantiles": 5,
            "rebalances": ["daily"],
            "cost_bands": [0.0, 10.0],
        },
        start=start,
        end=end,
    )

    result = execute_factor_sweep(str(run.id))

    assert result["status"] == "success"
    res = result["result"]
    assert len(res["metric_table"]) > 0
    dims = {p["param"] for p in res["param_impacts"]}
    assert {"factor", "window", "cost_bps"} <= dims
    db_session.refresh(run)
    assert run.status == "success"
    assert run.result_json is not None


def test_execute_factor_sweep_missing_prices_failed(db_session: Session) -> None:
    user = _make_user(db_session, "U6")
    bare = _make_asset(db_session, f"{PREFIX}-BARE2")
    run = _make_run(
        db_session,
        user,
        run_kind="factor_sweep",
        config={
            "universe": [str(bare.id)],
            "source": SRC,
            "start": "2023-01-02",
            "end": "2023-02-01",
            "price_field": "adjusted",
            "factors": ["momentum"],
            "top_ks": [1],
            "quantiles": [],
            "n_quantiles": 5,
            "rebalances": ["daily"],
            "cost_bands": [0.0],
        },
        start=date(2023, 1, 2),
        end=date(2023, 2, 1),
    )

    with pytest.raises(ValueError):
        execute_factor_sweep(str(run.id))

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_message is not None


def test_execute_wrong_run_kind_failed(db_session: Session) -> None:
    """run_kind 不匹配期望 → failed(防 worker 误调度到错误 kind 的 run)。"""
    user = _make_user(db_session, "U7")
    assets, start, end = _seed_universe(db_session)
    # 标 factor_compute 但调 quantile executor。
    run = _make_run(
        db_session,
        user,
        run_kind="factor_compute",
        config={
            "universe": [str(a.id) for a in assets],
            "source": SRC,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "price_field": "adjusted",
            "factor_name": "momentum_21",
            "n_quantiles": 5,
        },
        start=start,
        end=end,
    )

    with pytest.raises(ValueError, match="expected 'factor_quantile'"):
        execute_factor_quantile(str(run.id))

    db_session.refresh(run)
    assert run.status == "failed"


def test_execute_run_not_found_raises(db_session: Session) -> None:
    with pytest.raises(ValueError, match="not found"):
        execute_factor_compute(str(uuid.uuid4()))


# ===========================================================================
# API 层:POST *-async (mock queue) + GET /factors/jobs/{id}
# ===========================================================================


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    # mock queue:只验 run 创建 + enqueue 调用,不真跑 worker(同 test_backtest_api)。
    app.dependency_overrides[get_backtest_queue] = lambda: MagicMock()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _register(client: TestClient, suffix: str) -> tuple[str, uuid.UUID]:
    email = f"{PREFIX}-{suffix}@example.com"
    reg = client.post("/auth/register", json={"email": email, "password": "supersecretpw"})
    assert reg.status_code == 201, reg.text
    r = client.post("/auth/login", json={"email": email, "password": "supersecretpw"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"], uuid.UUID(reg.json()["id"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def seeded(client: TestClient, db_session: Session) -> tuple[str, list[uuid.UUID], str, str]:
    token, _ = _register(client, "A1")
    assets, start, end = _seed_universe(db_session)
    return token, [a.id for a in assets], start.isoformat(), end.isoformat()


def test_compute_async_enqueue_202(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/compute-async",
        json={
            "name": f"{PREFIX}-job1",
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": start,
            "end": end,
            "factor_names": ["momentum_21"],
        },
        headers=_auth(token),
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["run_kind"] == "factor_compute"
    assert body["status"] == "pending"
    run_id = uuid.UUID(body["run_id"])

    # GET 轮询:pending + config_snapshot 完整(可复现)。
    g = client.get(f"/factors/jobs/{run_id}", headers=_auth(token))
    assert g.status_code == 200
    gbody = g.json()
    assert gbody["status"] == "pending"
    assert gbody["run_kind"] == "factor_compute"
    assert gbody["result"] is None
    assert gbody["config_snapshot"]["factor_names"] == ["momentum_21"]


def test_quantile_async_enqueue_202(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/quantile-backtest-async",
        json={
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": start,
            "end": end,
            "factor_name": "momentum_21",
            "n_quantiles": 5,
        },
        headers=_auth(token),
    )
    assert r.status_code == 202
    assert r.json()["run_kind"] == "factor_quantile"


def test_sensitivity_async_enqueue_202(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/sensitivity-async",
        json={
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": start,
            "end": end,
            "factors": ["momentum"],
            "windows": {"momentum": [21]},
            "top_ks": [1, 3],
            "rebalances": ["daily"],
            "cost_bands": [0.0, 10.0],
        },
        headers=_auth(token),
    )
    assert r.status_code == 202
    assert r.json()["run_kind"] == "factor_sweep"


def test_get_job_success_returns_result(
    client: TestClient, db_session: Session, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    """模拟 worker 跑完写库(success + result_json)后,GET 返回结果(轮询 success)。"""
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/compute-async",
        json={
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": start,
            "end": end,
            "factor_names": ["momentum_21"],
        },
        headers=_auth(token),
    )
    run_id = uuid.UUID(r.json()["run_id"])

    # 模拟 worker 执行(真跑 service 层:跨 session 写 result_json + status)。
    execute_factor_compute(str(run_id))
    # db_session 缓存了 pending run(worker 用独立 session 写),失效后 GET 重查。
    db_session.expire_all()

    g = client.get(f"/factors/jobs/{run_id}", headers=_auth(token))
    assert g.status_code == 200
    body = g.json()
    assert body["status"] == "success"
    assert body["result"] is not None
    assert body["result"]["rows_written"] > 0
    assert body["error_message"] is None


def test_get_job_failed_returns_error(
    client: TestClient, db_session: Session, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    """数据不足 → worker failed + error_message,GET 返回可读失败原因(轮询 failed)。"""
    token, _, start, end = seeded
    bare = _make_asset(db_session, f"{PREFIX}-BARE3")  # 无 ohlcv
    r = client.post(
        "/factors/compute-async",
        json={
            "universe": [str(bare.id)],
            "source": SRC,
            "start": start,
            "end": end,
            "factor_names": ["momentum_21"],
        },
        headers=_auth(token),
    )
    run_id = uuid.UUID(r.json()["run_id"])

    # worker 执行:数据不足 → failed + error_message(re-raise 被吞,这里直接调)。
    with contextlib.suppress(ValueError):
        execute_factor_compute(str(run_id))
    db_session.expire_all()

    g = client.get(f"/factors/jobs/{run_id}", headers=_auth(token))
    assert g.status_code == 200
    body = g.json()
    assert body["status"] == "failed"
    assert body["error_message"] is not None
    assert body["result"] is None


def test_get_job_other_user_404(
    client: TestClient, db_session: Session, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/compute-async",
        json={
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": start,
            "end": end,
            "factor_names": ["momentum_21"],
        },
        headers=_auth(token),
    )
    run_id = r.json()["run_id"]

    other_token, _ = _register(client, "A2")  # 他人
    g = client.get(f"/factors/jobs/{run_id}", headers=_auth(other_token))
    assert g.status_code == 404  # ownership:他人 job 不可见(无存在泄露)


def test_get_job_not_factor_run_404(
    client: TestClient, db_session: Session, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    """普通 backtest run(kind=backtest)不能经 /factors/jobs 访问 → 404。"""
    token, user_id = _register(client, "A3")
    run = BacktestRun(
        user_id=user_id,
        name=f"{PREFIX}-plain-bt",
        strategy_type="buy_hold",
        config_json={"strategy_name": "buy_hold"},
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 5),
        price_field="adjusted",
        status="success",
        run_kind="backtest",
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    g = client.get(f"/factors/jobs/{run.id}", headers=_auth(token))
    assert g.status_code == 404


def test_compute_async_unknown_factor_422(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/compute-async",
        json={
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": start,
            "end": end,
            "factor_names": ["bogus"],
        },
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_compute_async_unauth_401(client: TestClient) -> None:
    r = client.post(
        "/factors/compute-async",
        json={
            "universe": [str(uuid.uuid4())],
            "source": SRC,
            "start": "2023-01-02",
            "end": "2023-02-01",
            "factor_names": ["momentum_21"],
        },
    )
    assert r.status_code == 401
