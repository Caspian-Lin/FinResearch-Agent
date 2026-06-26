"""Factor research API tests (FRA-56) — TestClient + real DB session + auth.

Seed 5 NASDAQ assets with ~50 business days of trending ohlcv, then exercise
the five factor endpoints (compute / values / ic / quantile-backtest /
sensitivity) on happy paths and the 422 / 404 error paths. Mirrors the
``test_backtest_api.py`` client/register/asset pattern.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.asset import Asset
from app.models.ohlcv import Ohlcv
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

PREFIX = "FRA56TEST"
SRC = "FRA56SRC"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    owned = "SELECT id FROM assets WHERE symbol LIKE :p"
    db.execute(text(f"DELETE FROM factor_values WHERE asset_id IN ({owned})"), {"p": f"{PREFIX}%"})
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


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _register(client: TestClient, suffix: str) -> str:
    email = f"{PREFIX}-{suffix}@example.com"
    reg = client.post("/auth/register", json={"email": email, "password": "supersecretpw"})
    assert reg.status_code == 201, reg.text
    r = client.post("/auth/login", json={"email": email, "password": "supersecretpw"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


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


def _add_bar(db: Session, asset_id: uuid.UUID, day: date, price: int) -> None:
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


@pytest.fixture()
def seeded(client: TestClient, db_session: Session) -> tuple[str, list[uuid.UUID], str, str]:
    """Register a user + seed 5 NASDAQ assets (distinct drifts) with 50 business
    days of bars. Returns (token, asset_ids, start_iso, end_iso)."""
    token = _register(client, "U1")
    drifts = [0.003, 0.0015, 0.0, -0.0015, -0.003]
    assets = [_make_asset(db_session, f"{PREFIX}-{chr(ord('A') + i)}") for i in range(5)]
    days = pd.bdate_range("2023-01-02", periods=50)
    for j, day_ts in enumerate(days):
        day = day_ts.date()
        for asset, drift in zip(assets, drifts, strict=True):
            price = round(100 * ((1 + drift) ** j))
            _add_bar(db_session, asset.id, day, price)
    db_session.commit()
    return token, [a.id for a in assets], days[0].date().isoformat(), days[-1].date().isoformat()


# ---------------------------------------------------------------------------
# POST /factors/compute
# ---------------------------------------------------------------------------


def test_compute_then_values_roundtrip(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    body = {
        "universe": [str(a) for a in asset_ids],
        "source": SRC,
        "start": start,
        "end": end,
        "price_field": "adjusted",
        "factor_names": ["momentum_21", "rsi_14", "macd_hist"],
    }
    r = client.post("/factors/compute", json=body, headers=_auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["rows_written"] > 0
    assert set(data["factor_names"]) == {"momentum_21", "rsi_14", "macd_hist"}
    assert data["config_snapshot"]["price_field"] == "adjusted"

    # 读回 momentum_21 值。
    rv = client.get(
        "/factors/values",
        params={"factor_name": "momentum_21", "source": SRC, "limit": 5},
        headers=_auth(token),
    )
    assert rv.status_code == 200, rv.text
    vdata = rv.json()
    assert vdata["factor_name"] == "momentum_21"
    assert len(vdata["items"]) > 0
    assert {"asset_id", "factor_name", "time", "value", "source"} <= set(vdata["items"][0])


def test_compute_unknown_factor_422(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/compute",
        json={
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": start,
            "end": end,
            "factor_names": ["bogus_factor"],
        },
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_compute_universe_not_found_404(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, _, start, end = seeded
    r = client.post(
        "/factors/compute",
        json={
            "universe": [str(uuid.uuid4())],
            "source": SRC,
            "start": start,
            "end": end,
            "factor_names": ["momentum_21"],
        },
        headers=_auth(token),
    )
    assert r.status_code == 404


def test_compute_start_after_end_422(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/compute",
        json={
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": end,
            "end": start,
            "factor_names": ["momentum_21"],
        },
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_compute_insufficient_data_422(
    client: TestClient, db_session: Session, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, _, start, end = seeded
    # 新建一个 asset 但不 seed ohlcv → load_prices 数据不足。
    bare = _make_asset(db_session, f"{PREFIX}-BARE")
    r = client.post(
        "/factors/compute",
        json={
            "universe": [str(bare.id)],
            "source": SRC,
            "start": start,
            "end": end,
            "factor_names": ["momentum_21"],
        },
        headers=_auth(token),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /factors/{name}/ic
# ---------------------------------------------------------------------------


def test_ic_happy(client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]) -> None:
    token, asset_ids, start, end = seeded
    r = client.get(
        "/factors/momentum_21/ic",
        params={
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": start,
            "end": end,
            "horizon": 5,
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["factor_name"] == "momentum_21"
    summary = data["result"]["summary"]
    assert summary["n"] > 0
    assert "mean" in summary and "icir" in summary
    assert isinstance(data["result"]["series"], list)
    assert "horizon" in data["config_snapshot"]


def test_ic_macd_hist_happy(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.get(
        "/factors/macd_hist/ic",
        params={
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": start,
            "end": end,
            "horizon": 5,
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["factor_name"] == "macd_hist"
    assert data["result"]["summary"]["n"] > 0


def test_ic_unknown_factor_422(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.get(
        "/factors/bogus/ic",
        params={"universe": [str(a) for a in asset_ids], "source": SRC, "start": start, "end": end},
        headers=_auth(token),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /factors/quantile-backtest
# ---------------------------------------------------------------------------


def test_quantile_backtest_happy(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/quantile-backtest",
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
    assert r.status_code == 200, r.text
    data = r.json()
    result = data["result"]
    assert set(result["quantile_equity"].keys()) == {"1", "2", "3", "4", "5"}
    assert isinstance(result["top_minus_bottom"], list)
    assert isinstance(result["monotonicity"], float)
    assert data["config_snapshot"]["n_quantiles"] == 5


def test_quantile_backtest_macd_hist_happy(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/quantile-backtest",
        json={
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": start,
            "end": end,
            "factor_name": "macd_hist",
            "n_quantiles": 5,
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["factor_name"] == "macd_hist"
    assert set(data["result"]["quantile_equity"].keys()) == {"1", "2", "3", "4", "5"}


def test_quantile_backtest_unknown_factor_422(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/quantile-backtest",
        json={
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": start,
            "end": end,
            "factor_name": "bogus",
            "n_quantiles": 5,
        },
        headers=_auth(token),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /factors/sensitivity
# ---------------------------------------------------------------------------


def test_sensitivity_happy(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/sensitivity",
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
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["metric_table"]) > 0
    dims = {p["param"] for p in data["param_impacts"]}
    assert "factor" in dims and "window" in dims and "cost_bps" in dims
    assert "best_net_sharpe" in data
    assert data["config_snapshot"]["factors"] == ["momentum"]


def test_sensitivity_unknown_factor_type_422(
    client: TestClient, seeded: tuple[str, list[uuid.UUID], str, str]
) -> None:
    token, asset_ids, start, end = seeded
    r = client.post(
        "/factors/sensitivity",
        json={
            "universe": [str(a) for a in asset_ids],
            "source": SRC,
            "start": start,
            "end": end,
            "factors": ["bogus"],
        },
        headers=_auth(token),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# auth required
# ---------------------------------------------------------------------------


def test_compute_requires_auth(client: TestClient) -> None:
    r = client.post(
        "/factors/compute",
        json={
            "universe": [str(uuid.uuid4())],
            "source": SRC,
            "start": "2023-01-02",
            "end": "2023-02-01",
            "factor_names": ["momentum_21"],
        },
    )
    assert r.status_code == 401
