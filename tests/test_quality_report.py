"""Real-Postgres tests for the OHLCV data-quality report API (FRA-9).

Covers ``GET /quality/{asset_id}``: expected-session counting against the
real NYSE calendar (holidays/weekends excluded), coverage computation,
missing-day listing, the five anomaly rules, source isolation, and the
404/422 error paths.

The shared host Postgres is used; cleanup is surgical (only rows whose asset
symbol starts with ``FRA9TEST``). Fixtures live in this file only —
``tests/conftest.py`` is left untouched to avoid merge conflicts with
parallel work, mirroring ``test_ohlcv_api.py``. Test bars are inserted
directly via the ``Ohlcv`` model; this suite does not depend on the FRA-8 sync
service and uses the real ``exchange_calendars`` (no mocking).
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

TEST_PREFIX = "FRA9TEST"

# Fixed window: NYSE 2024-01-01..2024-01-12. Expected trading sessions are
# 01-02,03,04,05,08,09,10,11,12 (9 days; 01-01 New Year holiday and the
# 01-06/07 weekend are excluded).
WINDOW_START = "2024-01-01"
WINDOW_END = "2024-01-12"


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


def _make_asset(db: Session, symbol: str = "FRA9TEST-AAPL", exchange: str = "NYSE") -> Asset:
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


def _quality(client: TestClient, asset_id: uuid.UUID, source: str = "yfinance") -> dict:
    """Call ``GET /quality/{asset_id}`` over the fixed NYSE window."""
    resp = client.get(
        f"/quality/{asset_id}",
        params={"source": source, "start": WINDOW_START, "end": WINDOW_END},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Expected sessions / coverage / missing
# ---------------------------------------------------------------------------


def test_expected_sessions_excludes_holiday_and_weekend(
    client: TestClient, db_session: Session
) -> None:
    """NYSE 2024-01-01..01-12 has 9 sessions (New Year + weekend excluded)."""
    asset = _make_asset(db_session, "FRA9TEST-EXP", exchange="NYSE")
    for day in (
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
        date(2024, 1, 5),
        date(2024, 1, 8),
        date(2024, 1, 9),
        date(2024, 1, 10),
        date(2024, 1, 11),
        date(2024, 1, 12),
    ):
        _insert_bar(db_session, asset.id, day)

    report = _quality(client, asset.id)
    assert report["expected_sessions"] == 9
    assert report["observed_sessions"] == 9
    assert report["coverage"] == 1.0
    assert report["missing_sessions"] == []
    assert report["missing_sessions_count"] == 0


def test_coverage_and_missing(client: TestClient, db_session: Session) -> None:
    """6 of 9 expected sessions present -> coverage 6/9, 3 missing days."""
    asset = _make_asset(db_session, "FRA9TEST-COV", exchange="NYSE")
    for day in (
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
        date(2024, 1, 8),
        date(2024, 1, 9),
        date(2024, 1, 10),
    ):
        _insert_bar(db_session, asset.id, day)

    report = _quality(client, asset.id)
    assert report["expected_sessions"] == 9
    assert report["observed_sessions"] == 6
    assert report["missing_sessions_count"] == 3
    assert report["missing_sessions"] == [
        "2024-01-05",
        "2024-01-11",
        "2024-01-12",
    ]
    assert report["coverage"] == pytest.approx(6 / 9)


# ---------------------------------------------------------------------------
# Anomaly rules
# ---------------------------------------------------------------------------


def test_anomaly_non_positive_price(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA9TEST-NPP", exchange="NYSE")
    _insert_bar(db_session, asset.id, date(2024, 1, 2), close="-1")

    report = _quality(client, asset.id)
    assert any(a["rule"] == "non_positive_price" for a in report["anomalies"])


def test_anomaly_high_lt_low(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA9TEST-HLL", exchange="NYSE")
    _insert_bar(db_session, asset.id, date(2024, 1, 2), high="50", low="99")

    report = _quality(client, asset.id)
    assert any(a["rule"] == "high_lt_low" for a in report["anomalies"])


def test_anomaly_negative_volume(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA9TEST-NEG", exchange="NYSE")
    _insert_bar(db_session, asset.id, date(2024, 1, 2), volume=-5)

    report = _quality(client, asset.id)
    assert any(a["rule"] == "negative_volume" for a in report["anomalies"])


def test_anomaly_zero_volume(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA9TEST-ZV", exchange="NYSE")
    _insert_bar(db_session, asset.id, date(2024, 1, 2), volume=0)

    report = _quality(client, asset.id)
    assert any(a["rule"] == "zero_volume" for a in report["anomalies"])


def test_anomaly_large_return(client: TestClient, db_session: Session) -> None:
    """A 30% day-over-day move (>20% threshold) flags large_return."""
    asset = _make_asset(db_session, "FRA9TEST-LR", exchange="NYSE")
    _insert_bar(db_session, asset.id, date(2024, 1, 2), close="100")
    _insert_bar(db_session, asset.id, date(2024, 1, 3), close="130")  # +30%

    report = _quality(client, asset.id)
    assert any(a["rule"] == "large_return" for a in report["anomalies"])


# ---------------------------------------------------------------------------
# Source isolation
# ---------------------------------------------------------------------------


def test_separate_sources_not_mixed(client: TestClient, db_session: Session) -> None:
    """A yfinance report must not count bars stored under a different source."""
    asset = _make_asset(db_session, "FRA9TEST-SRC", exchange="NYSE")
    # yfinance owns 3 sessions
    for day in (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)):
        _insert_bar(db_session, asset.id, day, source="yfinance")
    # manual owns a different set of sessions
    for day in (date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 9)):
        _insert_bar(db_session, asset.id, day, source="manual")

    yf = _quality(client, asset.id, source="yfinance")
    man = _quality(client, asset.id, source="manual")
    assert yf["observed_sessions"] == 3
    assert man["observed_sessions"] == 3
    # The two sources never overlap, so combined coverage is not reported —
    # but each source only sees its own bars.
    assert yf["missing_sessions"] == [
        "2024-01-05",
        "2024-01-08",
        "2024-01-09",
        "2024-01-10",
        "2024-01-11",
        "2024-01-12",
    ]
    assert man["missing_sessions"] == [
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
        "2024-01-10",
        "2024-01-11",
        "2024-01-12",
    ]


# ---------------------------------------------------------------------------
# Error paths (404 / 422)
# ---------------------------------------------------------------------------


def test_unknown_asset_returns_404(client: TestClient) -> None:
    resp = client.get(
        f"/quality/{uuid.uuid4()}",
        params={"source": "yfinance", "start": WINDOW_START, "end": WINDOW_END},
    )
    assert resp.status_code == 404


def test_start_after_end_returns_422(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA9TEST-SGT", exchange="NYSE")
    resp = client.get(
        f"/quality/{asset.id}",
        params={"source": "yfinance", "start": "2024-01-12", "end": "2024-01-01"},
    )
    assert resp.status_code == 422


def test_unsupported_exchange_returns_422(client: TestClient, db_session: Session) -> None:
    """An exchange with no known calendar yields 422, not 500."""
    asset = _make_asset(db_session, "FRA9TEST-MARS", exchange="MARS")
    resp = client.get(
        f"/quality/{asset.id}",
        params={"source": "yfinance", "start": WINDOW_START, "end": WINDOW_END},
    )
    assert resp.status_code == 422
