"""Real-Postgres tests for the OHLCV read API (FRA-15).

Covers ``GET /ohlcv``: filtering by source, the ``[start, end]`` time window
(end inclusive), keyset cursor pagination (no duplicates, no gaps), the empty
page shape, and the 404/422 error paths.

The shared host Postgres is used; cleanup is surgical (only rows whose asset
symbol starts with ``FRA15TEST``). Fixtures live in this file only —
``tests/conftest.py`` is left untouched to avoid merge conflicts with parallel
work, mirroring ``test_ohlcv_ingestion.py``. Test bars are inserted directly
via the ``Ohlcv`` model; this suite does not depend on the FRA-8 sync service.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.asset import Asset
from app.models.ohlcv import Ohlcv
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

TEST_PREFIX = "FRA15TEST"


# ---------------------------------------------------------------------------
# DB helpers + fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    """Delete only rows owned by this suite (ohlcv via their owning assets)."""
    db.execute(
        text("DELETE FROM ohlcv WHERE asset_id IN (SELECT id FROM assets WHERE symbol LIKE :p)"),
        {"p": f"{TEST_PREFIX}%"},
    )
    db.execute(text("DELETE FROM assets WHERE symbol LIKE :p"), {"p": f"{TEST_PREFIX}%"})
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
        try:
            yield db_session
        finally:
            # Fixture owns the session lifecycle; do not close here.
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _make_asset(db: Session, symbol: str = "FRA15TEST-AAPL", exchange: str = "NASDAQ") -> Asset:
    asset = Asset(
        symbol=symbol,
        name=f"Test {symbol}",
        exchange=exchange,
        asset_type="stock",
        currency="USD",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _insert_bar(
    db: Session,
    asset_id: uuid.UUID,
    day: date,
    source: str = "yfinance",
    *,
    open_: str = "100",
    high: str = "101",
    low: str = "99",
    close: str = "100",
    adjusted_close: str | None = "100",
    volume: int = 1000,
) -> Ohlcv:
    """Insert one OHLCV bar at UTC midnight of ``day`` and commit."""
    bar = Ohlcv(
        asset_id=asset_id,
        source=source,
        time=datetime(day.year, day.month, day.day, tzinfo=UTC),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        adjusted_close=Decimal(adjusted_close) if adjusted_close is not None else None,
        volume=volume,
    )
    db.add(bar)
    db.commit()
    return bar


# ---------------------------------------------------------------------------
# Source filter + time window
# ---------------------------------------------------------------------------


def test_list_ohlcv_filters_by_source(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA15TEST-SRC")
    _insert_bar(db_session, asset.id, date(2024, 1, 2), source="yfinance", close="100")
    _insert_bar(db_session, asset.id, date(2024, 1, 3), source="manual", close="200")

    resp = client.get("/ohlcv", params={"asset_id": str(asset.id), "source": "yfinance"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["source"] == "yfinance"
    # Numeric(20,6) column stores trailing scale; compare by value, not string.
    assert Decimal(body["items"][0]["close"]) == Decimal("100")


def test_list_ohlcv_time_window(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA15TEST-WIN")
    for day in range(2, 7):  # 2024-01-02 .. 2024-01-06
        _insert_bar(db_session, asset.id, date(2024, 1, day), close=str(100 + day))

    resp = client.get(
        "/ohlcv",
        params={
            "asset_id": str(asset.id),
            "start": "2024-01-03",
            "end": "2024-01-05",
        },
    )
    assert resp.status_code == 200
    days = {item["time"][:10] for item in resp.json()["items"]}
    assert days == {"2024-01-03", "2024-01-04", "2024-01-05"}


# ---------------------------------------------------------------------------
# Keyset cursor pagination
# ---------------------------------------------------------------------------


def test_list_ohlcv_keyset_pagination_no_dup_no_gap(
    client: TestClient, db_session: Session
) -> None:
    asset = _make_asset(db_session, "FRA15TEST-PAGE")
    for day in range(2, 7):  # 5 bars: 2024-01-02 .. 2024-01-06
        _insert_bar(db_session, asset.id, date(2024, 1, day), close=str(100 + day))

    seen: list[dict] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, object] = {"asset_id": str(asset.id), "limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        resp = client.get("/ohlcv", params=params)
        assert resp.status_code == 200
        body = resp.json()
        seen.extend(body["items"])
        pages += 1
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break
        cursor = body["next_cursor"]
        assert pages < 20  # safety against an infinite loop

    times = [item["time"][:10] for item in seen]
    assert len(seen) == 5
    assert len(set(times)) == 5  # no duplicates
    assert set(times) == {
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
        "2024-01-05",
        "2024-01-06",
    }


def test_list_ohlcv_empty_returns_empty(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA15TEST-EMPTY")
    resp = client.get("/ohlcv", params={"asset_id": str(asset.id)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["next_cursor"] is None
    assert body["has_more"] is False


def test_list_ohlcv_response_fields(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA15TEST-FIELDS")
    _insert_bar(
        db_session,
        asset.id,
        date(2024, 1, 2),
        close="100.5",
        adjusted_close="99.5",
        volume=1234,
    )
    resp = client.get("/ohlcv", params={"asset_id": str(asset.id)})
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    # Numeric(20,6) column stores trailing scale; compare by value, not string.
    assert Decimal(item["adjusted_close"]) == Decimal("99.5")
    assert Decimal(item["close"]) == Decimal("100.5")
    assert item["volume"] == 1234
    assert set(item) >= {
        "asset_id",
        "time",
        "source",
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
    }


# ---------------------------------------------------------------------------
# Error paths (404 / 422)
# ---------------------------------------------------------------------------


def test_list_ohlcv_unknown_asset_returns_404(client: TestClient) -> None:
    resp = client.get("/ohlcv", params={"asset_id": str(uuid.uuid4())})
    assert resp.status_code == 404


def test_list_ohlcv_start_after_end_returns_422(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA15TEST-422")
    resp = client.get(
        "/ohlcv",
        params={
            "asset_id": str(asset.id),
            "start": "2024-01-05",
            "end": "2024-01-01",
        },
    )
    assert resp.status_code == 422


def test_list_ohlcv_invalid_cursor_returns_422(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA15TEST-CUR")
    resp = client.get(
        "/ohlcv",
        params={"asset_id": str(asset.id), "cursor": "not-valid-base64"},
    )
    assert resp.status_code == 422


def test_list_ohlcv_missing_asset_id_returns_422(client: TestClient) -> None:
    resp = client.get("/ohlcv")
    assert resp.status_code == 422
