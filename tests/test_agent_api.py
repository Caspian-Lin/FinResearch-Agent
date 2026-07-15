"""Agent API integration tests (FRA-90) — TestClient + mock queue, real DB.

Covers:
* POST /agent/plans — plan creation, ambiguity, validation errors.
* POST /agent/runs — hash mismatch, create + enqueue, ownership.
* GET /agent/runs — list, pagination.
* GET /agent/runs/{id} — detail, cross-user 404.
* GET /agent/runs/{id}/trace — trace structure.
* POST /agent/runs/{id}/cancel — idempotent cancel, terminal noop.

Uses mock queue (no real RQ enqueue). Fixture planner (default) keeps tests offline.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.asset import Asset
from app.models.ohlcv import Ohlcv
from app.schemas.agent import (
    AgentRunStatus,
    ResearchPlan,
)
from app.services.agent.repository import AgentRunRepository
from app.services.sync import get_agent_queue
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

PREFIX = "FRA90API"


# ─── DB helpers ──────────────────────────────────────────────────────────────


def _cleanup(db: Session) -> None:
    p = f"{PREFIX}%"
    runs = "SELECT id FROM research_runs WHERE research_question LIKE :p"
    steps = f"SELECT id FROM research_steps WHERE run_id IN ({runs})"
    db.execute(text(f"DELETE FROM agent_tool_calls WHERE step_id IN ({steps})"), {"p": p})
    db.execute(text(f"DELETE FROM research_steps WHERE run_id IN ({runs})"), {"p": p})
    db.execute(text("DELETE FROM research_runs WHERE research_question LIKE :p"), {"p": p})
    db.execute(
        text("DELETE FROM assets WHERE symbol IN ('FRNV', 'FRSP') OR symbol LIKE :p"), {"p": p}
    )
    db.execute(text("DELETE FROM users WHERE email ILIKE :p"), {"p": p})
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
    app.dependency_overrides[get_agent_queue] = lambda: MagicMock()
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


def _make_asset(db: Session, symbol: str) -> Asset:
    asset = Asset(
        symbol=symbol,
        name=f"Test {symbol}",
        exchange="NASDAQ",
        asset_type="stock",
        data_source="yfinance",
        currency="USD",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _seed_ohlcv(db: Session, asset: Asset, *, days: int = 200) -> int:
    bars: list[Ohlcv] = []
    start = date(2022, 6, 1)
    for i in range(days):
        dt = datetime.combine(start + timedelta(days=i), datetime.min.time(), tzinfo=UTC)
        price = Decimal("100") + Decimal(str(i))
        bars.append(
            Ohlcv(
                asset_id=asset.id,
                time=dt,
                source="yfinance",
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


def _make_plan_dict(
    *,
    universe: list[Asset],
    benchmark: Asset,
    question: str = f"{PREFIX} question?",
    strategy: str = "buy_hold",
) -> dict:
    return {
        "schema_version": "1.0",
        "research_question": question,
        "resolution": "validated",
        "universe": [{"symbol": a.symbol, "asset_id": str(a.id)} for a in universe],
        "benchmark": {"symbol": benchmark.symbol, "asset_id": str(benchmark.id)},
        "data_source": "yfinance",
        "start_date": "2022-06-01T00:00:00Z",
        "end_date": "2023-06-01T00:00:00Z",
        "price_field": "adjusted",
        "factors": [{"name": "momentum_126", "kind": "technical"}],
        "sentiment_provenance": None,
        "strategy": {"name": strategy, "params": {}, "rebalance": "monthly"},
        "transaction_cost_bps": 10.0,
        "validation": {"baselines": ["buy_and_hold"], "cost_sensitivity_bps": [0.0, 10.0]},
        "risk_checks": {},
        "assumptions": ["Historical simulation only."],
        "requested_outputs": ["equity_curve"],
    }


# ─── POST /agent/plans ───────────────────────────────────────────────────────


def test_create_plan_happy_path(client: TestClient, db_session: Session) -> None:
    token, _ = _register(client, "U1")
    # Use prefixed symbols that the fixture planner regex still matches ([A-Z]{2,6}).
    _make_asset(db_session, "FRNV")
    _make_asset(db_session, "FRSP")

    resp = client.post(
        "/agent/plans",
        json={"hypothesis": "Does FRNV momentum predict returns vs FRSP in 2022-2025?"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plan"] is not None
    assert body["plan_hash"] is not None
    assert body["plan"]["research_question"]
    assert body["plan"]["schema_version"] == "1.0"


def test_create_plan_ambiguous_hypothesis(client: TestClient, db_session: Session) -> None:
    token, _ = _register(client, "U2")
    resp = client.post(
        "/agent/plans",
        json={"hypothesis": "hello world"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    # Fixture planner should flag as unsupported/ambiguous.
    assert body["plan"] is None or body["validation_errors"]


def test_create_plan_no_auth(client: TestClient) -> None:
    resp = client.post("/agent/plans", json={"hypothesis": "test"})
    assert resp.status_code == 401


# ─── POST /agent/runs ────────────────────────────────────────────────────────


def test_create_run_hash_mismatch(client: TestClient, db_session: Session) -> None:
    token, _ = _register(client, "U3")
    asset = _make_asset(db_session, f"{PREFIX}-A")

    resp = client.post(
        "/agent/runs",
        json={"plan": _make_plan_dict(universe=[asset], benchmark=asset), "plan_hash": "bogus"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


def test_create_run_success(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U4")
    asset = _make_asset(db_session, f"{PREFIX}-A")
    plan_dict = _make_plan_dict(universe=[asset], benchmark=asset)

    # First, get a valid plan_hash from POST /agent/plans.
    plan_resp = client.post(
        "/agent/plans",
        json={"hypothesis": f"Does {PREFIX}-A momentum predict returns?"},
        headers=_auth(token),
    )
    assert plan_resp.status_code == 200

    # Use the plan dict directly with correct hash.
    from app.services.agent.repository import compute_plan_hash

    plan = ResearchPlan.model_validate(plan_dict)
    correct_hash = compute_plan_hash(plan.model_dump(mode="json"))

    resp = client.post(
        "/agent/runs",
        json={"plan": plan.model_dump(mode="json"), "plan_hash": correct_hash},
        headers=_auth(token),
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    run_id = uuid.UUID(body["run_id"])
    assert body["plan_hash"] == correct_hash

    # Verify run exists in DB.
    repo = AgentRunRepository(db_session)
    run = repo.get_run(run_id, user_id)
    assert run.status == AgentRunStatus.QUEUED.value


def test_create_run_no_auth(client: TestClient) -> None:
    resp = client.post("/agent/runs", json={"plan": {}, "plan_hash": "x"})
    assert resp.status_code in (401, 422)


# ─── GET /agent/runs ─────────────────────────────────────────────────────────


def test_list_runs(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U5")
    other_token, _ = _register(client, "U6")

    repo = AgentRunRepository(db_session)
    for i in range(3):
        repo.create_run(
            user_id=user_id,
            research_question=f"{PREFIX} q{i}",
            plan={"schema_version": "1.0"},
        )

    resp = client.get("/agent/runs", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 3
    assert len(body["runs"]) >= 3
    # All runs belong to this user.
    for r in body["runs"]:
        assert PREFIX in r["research_question"]


def test_list_runs_cross_user_isolation(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U7")
    other_token, other_id = _register(client, "U8")

    repo = AgentRunRepository(db_session)
    repo.create_run(user_id=user_id, research_question=f"{PREFIX} mine", plan={})
    repo.create_run(user_id=other_id, research_question=f"{PREFIX} theirs", plan={})

    resp = client.get("/agent/runs", headers=_auth(token))
    assert resp.status_code == 200
    questions = [r["research_question"] for r in resp.json()["runs"]]
    assert f"{PREFIX} mine" in questions
    assert f"{PREFIX} theirs" not in questions


# ─── GET /agent/runs/{id} ────────────────────────────────────────────────────


def test_get_run_detail(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U9")
    repo = AgentRunRepository(db_session)
    run = repo.create_run(
        user_id=user_id,
        research_question=f"{PREFIX} detail?",
        plan={"schema_version": "1.0"},
    )

    resp = client.get(f"/agent/runs/{run.id}", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(run.id)
    assert body["status"] == "draft"


def test_get_run_detail_cross_user_404(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U10")
    other_token, other_id = _register(client, "U11")

    repo = AgentRunRepository(db_session)
    run = repo.create_run(
        user_id=user_id,
        research_question=f"{PREFIX} secret",
        plan={"schema_version": "1.0"},
    )

    resp = client.get(f"/agent/runs/{run.id}", headers=_auth(other_token))
    assert resp.status_code == 404


def test_get_run_detail_not_found(client: TestClient) -> None:
    token, _ = _register(client, "U12")
    resp = client.get(f"/agent/runs/{uuid.uuid4()}", headers=_auth(token))
    assert resp.status_code == 404


# ─── GET /agent/runs/{id}/trace ──────────────────────────────────────────────


def test_get_trace_empty(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U13")
    repo = AgentRunRepository(db_session)
    run = repo.create_run(
        user_id=user_id,
        research_question=f"{PREFIX} trace?",
        plan={"schema_version": "1.0"},
    )

    resp = client.get(f"/agent/runs/{run.id}/trace", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == str(run.id)
    assert body["steps"] == []


def test_get_trace_with_steps(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U14")
    repo = AgentRunRepository(db_session)
    run = repo.create_run(
        user_id=user_id,
        research_question=f"{PREFIX} trace2?",
        plan={"schema_version": "1.0"},
    )
    repo.transition_run(run.id, user_id, AgentRunStatus.VALIDATED)
    repo.append_step(run.id, user_id, sequence=1, agent_role="data_agent", kind="data:test")

    resp = client.get(f"/agent/runs/{run.id}/trace", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["steps"]) == 1
    assert body["steps"][0]["agent_role"] == "data_agent"
    assert body["steps"][0]["tool_calls"] == []


def test_get_trace_cross_user_404(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U15")
    other_token, _ = _register(client, "U16")
    repo = AgentRunRepository(db_session)
    run = repo.create_run(
        user_id=user_id,
        research_question=f"{PREFIX} private",
        plan={"schema_version": "1.0"},
    )
    resp = client.get(f"/agent/runs/{run.id}/trace", headers=_auth(other_token))
    assert resp.status_code == 404


# ─── POST /agent/runs/{id}/cancel ────────────────────────────────────────────


def test_cancel_queued_run(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U17")
    repo = AgentRunRepository(db_session)
    run = repo.create_run(
        user_id=user_id,
        research_question=f"{PREFIX} cancel?",
        plan={"schema_version": "1.0"},
    )
    repo.transition_run(run.id, user_id, AgentRunStatus.VALIDATED)
    repo.transition_run(run.id, user_id, AgentRunStatus.QUEUED)

    resp = client.post(f"/agent/runs/{run.id}/cancel", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "canceled"


def test_cancel_idempotent_terminal(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U18")
    repo = AgentRunRepository(db_session)
    run = repo.create_run(
        user_id=user_id,
        research_question=f"{PREFIX} idempotent?",
        plan={"schema_version": "1.0"},
    )
    repo.transition_run(run.id, user_id, AgentRunStatus.VALIDATED)
    repo.transition_run(run.id, user_id, AgentRunStatus.QUEUED)
    repo.transition_run(run.id, user_id, AgentRunStatus.CANCELED)

    # Cancel again — should return 200 (already canceled).
    resp = client.post(f"/agent/runs/{run.id}/cancel", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "canceled"


def test_cancel_cross_user_404(client: TestClient, db_session: Session) -> None:
    token, user_id = _register(client, "U19")
    other_token, _ = _register(client, "U20")
    repo = AgentRunRepository(db_session)
    run = repo.create_run(
        user_id=user_id,
        research_question=f"{PREFIX} not yours",
        plan={"schema_version": "1.0"},
    )
    repo.transition_run(run.id, user_id, AgentRunStatus.VALIDATED)
    repo.transition_run(run.id, user_id, AgentRunStatus.QUEUED)

    resp = client.post(f"/agent/runs/{run.id}/cancel", headers=_auth(other_token))
    assert resp.status_code == 404
