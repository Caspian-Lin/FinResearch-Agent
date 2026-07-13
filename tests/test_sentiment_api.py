"""Sentiment API tests (FRA-70) — endpoints + async job state machine.

Three layers:

1. service 层(``execute_sentiment_*``):real DB,直接调(不依赖 RQ/Redis),
   验证状态机 pending → running → success/failed、``result_json`` 写入。
2. API 层(sync endpoints):TestClient + real DB,验成功 / 校验 / auth。
3. API 层(async endpoints):TestClient + mock queue,验 202 + 轮询 + ownership。

PREFIX 清理覆盖 sentiment_scores / news_items / factor_values / backtest_runs /
ohlcv / assets / users。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.asset import Asset
from app.models.backtest import BacktestRun
from app.models.factor import FactorValue
from app.models.news import NewsItem as NewsItemModel
from app.models.news import SentimentScore as SentimentScoreModel
from app.models.user import User
from app.services.sentiment.jobs import (
    execute_sentiment_classify,
    execute_sentiment_factor,
)
from app.services.sync import get_data_queue
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

PREFIX = "FRA70TEST"


# ---------------------------------------------------------------------------
# DB helpers + fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    owned = "SELECT id FROM assets WHERE symbol LIKE :p"
    users = "SELECT id FROM users WHERE email ILIKE :p"
    db.execute(
        text(f"DELETE FROM sentiment_scores WHERE asset_id IN ({owned})"),
        {"p": f"{PREFIX}%"},
    )
    db.execute(
        text(f"DELETE FROM news_items WHERE asset_id IN ({owned})"),
        {"p": f"{PREFIX}%"},
    )
    db.execute(
        text(f"DELETE FROM factor_values WHERE asset_id IN ({owned})"),
        {"p": f"{PREFIX}%"},
    )
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


def _make_user(db: Session, suffix: str) -> User:
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
            source="FRA70SRC",
            open=Decimal(price),
            high=Decimal(price),
            low=Decimal(price),
            close=Decimal(price),
            adjusted_close=Decimal(price),
            volume=1000,
        )
    )


def _seed_ohlcv(db: Session, asset: Asset, days: int = 30) -> tuple[date, date]:
    """Seed OHLCV bars for an asset so trading calendar has sessions."""
    bdays = list(__import__("pandas").bdate_range("2024-01-02", periods=days))
    for j, d in enumerate(bdays):
        _add_bar(db, asset.id, d.date(), 100 + j)
    db.commit()
    return bdays[0].date(), bdays[-1].date()


def _insert_news(
    db: Session,
    asset: Asset,
    *,
    headline: str,
    published_at: datetime,
    source: str = "fixture",
) -> NewsItemModel:
    import hashlib

    item = NewsItemModel(
        asset_id=asset.id,
        source=source,
        published_at=published_at,
        headline=headline,
        headline_hash=hashlib.sha256(headline.encode()).hexdigest(),
        summary=None,
        url=None,
        provider_id=None,
        raw_payload={"provider": "test"},
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _insert_score(
    db: Session,
    news: NewsItemModel,
    *,
    model_name: str = "fixture-model",
    label: str = "positive",
    score: float = 0.5,
    confidence: float = 0.9,
) -> SentimentScoreModel:
    s = SentimentScoreModel(
        news_item_id=news.id,
        asset_id=news.asset_id,
        published_at=news.published_at,
        model_name=model_name,
        label=label,
        score=Decimal(str(score)),
        confidence=Decimal(str(confidence)),
        raw_response={"label": label, "score": score},
        params={"prompt_version": "test-v1"},
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _make_run(
    db: Session,
    user: User,
    *,
    run_kind: str,
    config: dict[str, Any],
    start: date,
    end: date,
    status: str = "pending",
) -> BacktestRun:
    run = BacktestRun(
        user_id=user.id,
        name=f"{PREFIX}-{run_kind}-{uuid.uuid4().hex[:6]}",
        strategy_type="sentiment",
        config_json=config,
        benchmark_asset_id=None,
        start_date=start,
        end_date=end,
        price_field="adjusted",
        status=status,
        run_kind=run_kind,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# ===========================================================================
# 1. service 层:execute_sentiment_* 状态机
# ===========================================================================


def test_execute_sentiment_factor_success(db_session: Session) -> None:
    """sentiment_factor job:读 scores → 计算因子 → 写 factor_values → success。"""
    user = _make_user(db_session, "J1")
    asset = _make_asset(db_session, f"{PREFIX}-FA")
    start, end = _seed_ohlcv(db_session, asset)
    news = _insert_news(
        db_session,
        asset,
        headline="Good news",
        published_at=datetime(2024, 1, 3, 10, 0, tzinfo=UTC),
    )
    _insert_score(db_session, news, score=0.8, label="positive")

    run = _make_run(
        db_session,
        user,
        run_kind="sentiment_factor",
        config={
            "universe": [str(asset.id)],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "model_name": "fixture-model",
        },
        start=start,
        end=end,
    )

    result = execute_sentiment_factor(str(run.id))

    assert result["status"] == "success"
    assert result["result"]["rows_written"] > 0
    db_session.refresh(run)
    assert run.status == "success"
    assert run.result_json is not None

    n = db_session.scalar(
        select(func.count())
        .select_from(FactorValue)
        .where(FactorValue.asset_id == asset.id)
        .where(FactorValue.factor_name == "sentiment_score")
    )
    assert n is not None and n > 0


def test_execute_sentiment_classify_success(db_session: Session) -> None:
    """sentiment_classify job:查 news → 分类 → 写 scores → success。"""
    user = _make_user(db_session, "J2")
    asset = _make_asset(db_session, f"{PREFIX}-FB")
    start, end = _seed_ohlcv(db_session, asset)
    _insert_news(
        db_session,
        asset,
        headline="Great news",
        published_at=datetime(2024, 1, 3, 10, 0, tzinfo=UTC),
    )

    run = _make_run(
        db_session,
        user,
        run_kind="sentiment_classify",
        config={
            "universe": [str(asset.id)],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "classifier": None,
        },
        start=start,
        end=end,
    )

    result = execute_sentiment_classify(str(run.id))

    assert result["status"] == "success"
    assert result["result"]["classified"] > 0
    db_session.refresh(run)
    assert run.status == "success"


def test_execute_wrong_run_kind_failed(db_session: Session) -> None:
    """run_kind 不匹配期望 → failed。"""
    user = _make_user(db_session, "J3")
    asset = _make_asset(db_session, f"{PREFIX}-FC")
    start, end = _seed_ohlcv(db_session, asset)

    run = _make_run(
        db_session,
        user,
        run_kind="sentiment_factor",
        config={
            "universe": [str(asset.id)],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "model_name": "fixture-model",
        },
        start=start,
        end=end,
    )

    with pytest.raises(ValueError, match="expected 'sentiment_classify'"):
        execute_sentiment_classify(str(run.id))

    db_session.refresh(run)
    assert run.status == "failed"


def test_execute_run_not_found_raises(db_session: Session) -> None:
    with pytest.raises(ValueError, match="not found"):
        execute_sentiment_factor(str(uuid.uuid4()))


# ===========================================================================
# 2/3. API 层:TestClient + mock queue
# ===========================================================================


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_data_queue] = lambda: MagicMock()
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
def seeded(client: TestClient, db_session: Session) -> tuple[str, Asset, date, date]:
    """Register user + seed one asset with OHLCV bars."""
    token, _ = _register(client, "A1")
    asset = _make_asset(db_session, f"{PREFIX}-SA")
    start, end = _seed_ohlcv(db_session, asset)
    return token, asset, start, end


# --- sync news sync --------------------------------------------------------


def test_news_sync_success(client: TestClient, seeded: tuple[str, Asset, date, date]) -> None:
    """POST /sentiment/news/sync with fixture provider → inserts news items."""
    token, asset, _, _ = seeded
    r = client.post(
        "/sentiment/news/sync",
        json={
            "universe": [str(asset.id)],
            "start": "2024-01-02T00:00:00Z",
            "end": "2024-01-10T00:00:00Z",
            "provider": "fixture",
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "fixture"
    assert "config_snapshot" in body


def test_news_sync_asset_not_found_404(client: TestClient) -> None:
    token, _ = _register(client, "A2")
    r = client.post(
        "/sentiment/news/sync",
        json={
            "universe": [str(uuid.uuid4())],
            "start": "2024-01-02T00:00:00Z",
            "end": "2024-01-10T00:00:00Z",
        },
        headers=_auth(token),
    )
    assert r.status_code == 404


def test_news_sync_start_gt_end_422(
    client: TestClient, seeded: tuple[str, Asset, date, date]
) -> None:
    token, asset, _, _ = seeded
    r = client.post(
        "/sentiment/news/sync",
        json={
            "universe": [str(asset.id)],
            "start": "2024-01-10T00:00:00Z",
            "end": "2024-01-02T00:00:00Z",
        },
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_news_sync_unauth_401(client: TestClient) -> None:
    r = client.post(
        "/sentiment/news/sync",
        json={
            "universe": [str(uuid.uuid4())],
            "start": "2024-01-02T00:00:00Z",
            "end": "2024-01-10T00:00:00Z",
        },
    )
    assert r.status_code == 401


# --- async news sync -------------------------------------------------------


def test_news_sync_async_enqueue_202(
    client: TestClient, seeded: tuple[str, Asset, date, date]
) -> None:
    token, asset, _, _ = seeded
    r = client.post(
        "/sentiment/news/sync-async",
        json={
            "universe": [str(asset.id)],
            "start": "2024-01-02T00:00:00Z",
            "end": "2024-01-10T00:00:00Z",
            "provider": "fixture",
        },
        headers=_auth(token),
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["run_kind"] == "sentiment_sync_news"
    assert body["status"] == "pending"
    run_id = uuid.UUID(body["run_id"])

    # GET 轮询:pending + config_snapshot。
    g = client.get(f"/sentiment/jobs/{run_id}", headers=_auth(token))
    assert g.status_code == 200
    gbody = g.json()
    assert gbody["status"] == "pending"
    assert gbody["run_kind"] == "sentiment_sync_news"
    assert gbody["result"] is None
    assert gbody["config_snapshot"]["provider"] == "fixture"


# --- GET news --------------------------------------------------------------


def test_list_news(
    client: TestClient, db_session: Session, seeded: tuple[str, Asset, date, date]
) -> None:
    token, asset, _, _ = seeded
    _insert_news(
        db_session,
        asset,
        headline="Test news 1",
        published_at=datetime(2024, 1, 3, 10, 0, tzinfo=UTC),
    )
    r = client.get(
        "/sentiment/news",
        params={"asset_id": str(asset.id)},
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(item["headline"] == "Test news 1" for item in body["items"])


def test_list_news_unauth_401(client: TestClient) -> None:
    r = client.get("/sentiment/news")
    assert r.status_code == 401


# --- sync classify ---------------------------------------------------------


def test_classify_success(
    client: TestClient, db_session: Session, seeded: tuple[str, Asset, date, date]
) -> None:
    token, asset, start, end = seeded
    _insert_news(
        db_session,
        asset,
        headline="Great news",
        published_at=datetime(2024, 1, 3, 10, 0, tzinfo=UTC),
    )
    r = client.post(
        "/sentiment/score",
        json={
            "universe": [str(asset.id)],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "classifier": "fixture",
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["classified"] > 0
    assert body["status"] in ("success", "success_no_data")
    assert "config_snapshot" in body


def test_classify_asset_not_found_404(client: TestClient) -> None:
    token, _ = _register(client, "A3")
    r = client.post(
        "/sentiment/score",
        json={
            "universe": [str(uuid.uuid4())],
            "start": "2024-01-02",
            "end": "2024-01-10",
        },
        headers=_auth(token),
    )
    assert r.status_code == 404


# --- async classify --------------------------------------------------------


def test_classify_async_enqueue_202(
    client: TestClient, seeded: tuple[str, Asset, date, date]
) -> None:
    token, asset, start, end = seeded
    r = client.post(
        "/sentiment/score-async",
        json={
            "universe": [str(asset.id)],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "classifier": "fixture",
        },
        headers=_auth(token),
    )
    assert r.status_code == 202, r.text
    assert r.json()["run_kind"] == "sentiment_classify"


# --- GET scores ------------------------------------------------------------


def test_list_scores(
    client: TestClient, db_session: Session, seeded: tuple[str, Asset, date, date]
) -> None:
    token, asset, _, _ = seeded
    news = _insert_news(
        db_session,
        asset,
        headline="Scored news",
        published_at=datetime(2024, 1, 3, 10, 0, tzinfo=UTC),
    )
    _insert_score(db_session, news, score=0.7, label="positive", model_name="fixture-model")
    r = client.get(
        "/sentiment/scores",
        params={"asset_id": str(asset.id), "model_name": "fixture-model"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    item = body["items"][0]
    assert item["score"] == 0.7
    assert item["label"] == "positive"
    assert item["headline"] == "Scored news"


# --- GET factor ------------------------------------------------------------


def test_get_factor(
    client: TestClient, db_session: Session, seeded: tuple[str, Asset, date, date]
) -> None:
    token, asset, start, end = seeded
    news = _insert_news(
        db_session,
        asset,
        headline="Factor news",
        published_at=datetime(2024, 1, 3, 10, 0, tzinfo=UTC),
    )
    _insert_score(db_session, news, score=0.6, label="positive", model_name="fixture-model")
    r = client.get(
        "/sentiment/factor",
        params={
            "universe": str(asset.id),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "model_name": "fixture-model",
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_name"] == "fixture-model"
    assert len(body["items"]) >= 1
    assert any(v["value"] == 0.6 for item in body["items"] for v in item["values"])


# --- POST factor/compute ---------------------------------------------------


def test_factor_compute_sync(
    client: TestClient, db_session: Session, seeded: tuple[str, Asset, date, date]
) -> None:
    token, asset, start, end = seeded
    news = _insert_news(
        db_session,
        asset,
        headline="Compute news",
        published_at=datetime(2024, 1, 3, 10, 0, tzinfo=UTC),
    )
    _insert_score(db_session, news, score=0.5, label="positive", model_name="fixture-model")
    r = client.post(
        "/sentiment/factor/compute",
        json={
            "universe": [str(asset.id)],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "model_name": "fixture-model",
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_name"] == "fixture-model"
    assert body["rows_written"] > 0
    assert body["status"] == "success"


# --- POST factor/compute-async ---------------------------------------------


def test_factor_compute_async_enqueue_202(
    client: TestClient, seeded: tuple[str, Asset, date, date]
) -> None:
    token, asset, start, end = seeded
    r = client.post(
        "/sentiment/factor/compute-async",
        json={
            "universe": [str(asset.id)],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "model_name": "fixture-model",
        },
        headers=_auth(token),
    )
    assert r.status_code == 202, r.text
    assert r.json()["run_kind"] == "sentiment_factor"


# --- GET summaries ---------------------------------------------------------


def test_get_summaries(
    client: TestClient, db_session: Session, seeded: tuple[str, Asset, date, date]
) -> None:
    token, asset, start, end = seeded
    news = _insert_news(
        db_session,
        asset,
        headline="Summary news",
        published_at=datetime(2024, 1, 3, 10, 0, tzinfo=UTC),
    )
    _insert_score(db_session, news, score=0.4, label="neutral", model_name="fixture-model")
    r = client.get(
        "/sentiment/summaries",
        params={
            "universe": str(asset.id),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "model_name": "fixture-model",
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_name"] == "fixture-model"
    assert body["total"] >= 1
    item = body["items"][0]
    assert item["news_count"] >= 1


# --- GET jobs/{run_id} -----------------------------------------------------


def test_get_job_after_worker_success(
    client: TestClient, db_session: Session, seeded: tuple[str, Asset, date, date]
) -> None:
    """模拟 worker 跑完写库后,GET 返回 success + result_json。"""
    token, asset, start, end = seeded
    r = client.post(
        "/sentiment/factor/compute-async",
        json={
            "universe": [str(asset.id)],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "model_name": "fixture-model",
        },
        headers=_auth(token),
    )
    run_id = uuid.UUID(r.json()["run_id"])

    # 模拟 worker 执行。
    execute_sentiment_factor(str(run_id))
    db_session.expire_all()

    g = client.get(f"/sentiment/jobs/{run_id}", headers=_auth(token))
    assert g.status_code == 200
    body = g.json()
    assert body["status"] == "success"
    assert body["result"] is not None
    assert body["error_message"] is None


def test_get_job_other_user_404(client: TestClient, seeded: tuple[str, Asset, date, date]) -> None:
    token, asset, start, end = seeded
    r = client.post(
        "/sentiment/factor/compute-async",
        json={
            "universe": [str(asset.id)],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "model_name": "fixture-model",
        },
        headers=_auth(token),
    )
    run_id = r.json()["run_id"]

    other_token, _ = _register(client, "A4")
    g = client.get(f"/sentiment/jobs/{run_id}", headers=_auth(other_token))
    assert g.status_code == 404


def test_get_job_not_sentiment_run_404(client: TestClient, db_session: Session) -> None:
    """普通 backtest run(kind=backtest)不能经 /sentiment/jobs 访问 → 404。"""
    token, user_id = _register(client, "A5")
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

    g = client.get(f"/sentiment/jobs/{run.id}", headers=_auth(token))
    assert g.status_code == 404


def test_get_job_unauth_401(client: TestClient) -> None:
    r = client.get(f"/sentiment/jobs/{uuid.uuid4()}")
    assert r.status_code == 401
