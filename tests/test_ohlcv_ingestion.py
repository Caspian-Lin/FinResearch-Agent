"""Real tests for OHLCV data ingestion (FRA-8).

Covers the yfinance adapter (field conversion, UTC normalization, retry
policy), the idempotent PostgreSQL upsert (insert/update counting, no
duplicates, revised-data overwrite), the ``sync_ohlcv`` task orchestration
(success / failure / unknown-asset), the RQ→status mapping + sanitized error
summary, and the ``/sync`` API (input validation + job-status polling).

yfinance is mocked throughout — no network. The shared host Postgres is used;
cleanup is surgical (only rows whose asset symbol starts with ``FRA8TEST``).

Fixtures live in this file only — ``tests/conftest.py`` is left untouched to
avoid merge conflicts with parallel work, mirroring ``test_assets_api.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
import requests
from app.api.sync import get_data_queue
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.asset import Asset
from app.models.ohlcv import Ohlcv
from app.services import yfinance as yf_svc
from app.services.ohlcv import upsert_ohlcv_bars
from app.services.sync import map_rq_status, parse_job_inputs, safe_error_summary
from app.services.yfinance import OhlcvBar, _to_utc_midnight, fetch_ohlcv
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_none
from worker.tasks.ohlcv import sync_ohlcv

TEST_PREFIX = "FRA8TEST"


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


def _make_asset(db: Session, symbol: str = "FRA8TEST-AAPL", exchange: str = "NASDAQ") -> Asset:
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


def _bar(
    day: str,
    close: str,
    adjusted_close: str | None = None,
    *,
    open_: str = "100",
    high: str = "101",
    low: str = "99",
    volume: int = 1000,
) -> OhlcvBar:
    d = date.fromisoformat(day)
    return OhlcvBar(
        time=datetime(d.year, d.month, d.day, tzinfo=UTC),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        adjusted_close=Decimal(adjusted_close) if adjusted_close is not None else None,
        volume=volume,
    )


def _df(rows: list[dict]) -> pd.DataFrame:
    """Build a yfinance-shaped DataFrame indexed by trading-day Timestamp."""
    df = pd.DataFrame(rows)
    df.index = pd.DatetimeIndex(pd.to_datetime(df["Date"]))
    return df.drop(columns=["Date"])


def _fast_retryer() -> Retrying:
    """No-wait retryer so retry tests don't actually sleep."""
    return Retrying(
        retry=retry_if_exception_type(yf_svc.RETRYABLE_EXCEPTIONS),
        wait=wait_none(),
        stop=stop_after_attempt(3),
        reraise=True,
    )


def _count_ohlcv(db: Session, asset_id: uuid.UUID) -> int:
    return int(
        db.scalar(select(func.count()).select_from(Ohlcv).where(Ohlcv.asset_id == asset_id)) or 0
    )


# ---------------------------------------------------------------------------
# yfinance adapter: UTC normalization + field conversion + retry
# ---------------------------------------------------------------------------


def test_to_utc_midnight_normalizes_any_timestamp_to_utc_zero() -> None:
    """Both naive and tz-aware timestamps collapse to UTC 00:00 of their date."""
    naive = pd.Timestamp("2024-01-02 09:30:00")
    aware = pd.Timestamp("2024-01-02 16:00:00", tz="America/New_York")
    for ts in (naive, aware):
        out = _to_utc_midnight(ts)
        assert out.utcoffset() == timedelta(0)
        assert (out.year, out.month, out.day) == (2024, 1, 2)
        assert (out.hour, out.minute, out.second) == (0, 0, 0)


def test_fetch_ohlcv_field_conversion_maps_close_and_adj_close(monkeypatch) -> None:
    """raw Close → close, Adj Close → adjusted_close (never swapped); time UTC."""
    df = _df(
        [
            {
                "Date": "2024-01-02",
                "Open": 100.0,
                "High": 101.0,
                "Low": 99.0,
                "Close": 100.5,
                "Adj Close": 99.5,
                "Volume": 1000,
            },
            {
                "Date": "2024-01-03",
                "Open": 100.5,
                "High": 102.0,
                "Low": 100.0,
                "Close": 101.5,
                "Adj Close": 100.5,
                "Volume": 1100,
            },
        ]
    )

    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, **kwargs: object) -> pd.DataFrame:
            assert kwargs["auto_adjust"] is False
            return df

    monkeypatch.setattr(yf_svc.yf, "Ticker", FakeTicker)

    bars = fetch_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 5))
    assert len(bars) == 2
    b0, b1 = bars
    assert b0.close == Decimal("100.5")  # raw Close
    assert b0.adjusted_close == Decimal("99.5")  # Adj Close
    assert b0.open == Decimal("100")
    assert b0.high == Decimal("101")
    assert b0.low == Decimal("99")
    assert b0.volume == 1000
    assert b0.time == datetime(2024, 1, 2, tzinfo=UTC)
    assert b1.time == datetime(2024, 1, 3, tzinfo=UTC)


def test_fetch_ohlcv_retries_transient_network_error(monkeypatch) -> None:
    """A connection error is retried; success on the 3rd attempt."""
    df = _df(
        [
            {
                "Date": "2024-01-02",
                "Open": 1,
                "High": 1,
                "Low": 1,
                "Close": 1,
                "Adj Close": 1,
                "Volume": 1,
            }
        ]
    )
    calls = {"n": 0}

    class FakeTicker:
        def history(self, **kwargs: object) -> pd.DataFrame:
            calls["n"] += 1
            if calls["n"] < 3:
                raise requests.exceptions.ConnectionError("transient boom")
            return df

    monkeypatch.setattr(yf_svc.yf, "Ticker", lambda symbol: FakeTicker())

    bars = fetch_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 5), retryer=_fast_retryer())
    assert len(bars) == 1
    assert calls["n"] == 3  # 2 failures retried, 3rd attempt succeeded


def test_fetch_ohlcv_empty_symbol_returns_empty_without_retry(monkeypatch) -> None:
    """A bad symbol yields an empty DataFrame — not retried, not raised."""
    calls = {"n": 0}

    class FakeTicker:
        def history(self, **kwargs: object) -> pd.DataFrame:
            calls["n"] += 1
            return pd.DataFrame()  # parameter error, not a transient failure

    monkeypatch.setattr(yf_svc.yf, "Ticker", lambda symbol: FakeTicker())

    bars = fetch_ohlcv("BOGUS", date(2024, 1, 1), date(2024, 1, 5), retryer=_fast_retryer())
    assert bars == []
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Idempotent upsert
# ---------------------------------------------------------------------------


def test_upsert_inserts_bars_and_returns_counts(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA8TEST-INS")
    bars = [_bar("2024-01-02", "100.5", "99.5"), _bar("2024-01-03", "101.5", "100.5")]

    inserted, updated = upsert_ohlcv_bars(db_session, asset.id, "yfinance", bars)
    db_session.commit()

    assert (inserted, updated) == (2, 0)
    rows = db_session.scalars(
        select(Ohlcv).where(Ohlcv.asset_id == asset.id).order_by(Ohlcv.time)
    ).all()
    assert len(rows) == 2
    assert rows[0].close == Decimal("100.5")
    assert rows[0].adjusted_close == Decimal("99.5")
    assert rows[0].source == "yfinance"
    assert rows[0].time == datetime(2024, 1, 2, tzinfo=UTC)


def test_upsert_is_idempotent_no_duplicate_rows(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA8TEST-IDEM")
    bars = [_bar("2024-01-02", "100"), _bar("2024-01-03", "101")]

    ins1, upd1 = upsert_ohlcv_bars(db_session, asset.id, "yfinance", bars)
    db_session.commit()
    ins2, upd2 = upsert_ohlcv_bars(db_session, asset.id, "yfinance", bars)
    db_session.commit()

    assert (ins1, upd1) == (2, 0)
    assert (ins2, upd2) == (0, 2)
    assert _count_ohlcv(db_session, asset.id) == 2


def test_upsert_overwrites_revised_data(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA8TEST-REV")
    upsert_ohlcv_bars(db_session, asset.id, "yfinance", [_bar("2024-01-02", "100", "100")])
    db_session.commit()

    inserted, updated = upsert_ohlcv_bars(
        db_session, asset.id, "yfinance", [_bar("2024-01-02", "150", "149")]
    )
    db_session.commit()

    assert (inserted, updated) == (0, 1)
    row = db_session.scalar(select(Ohlcv).where(Ohlcv.asset_id == asset.id))
    assert row.close == Decimal("150")
    assert row.adjusted_close == Decimal("149")


def test_upsert_empty_bars_is_noop(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA8TEST-EMPTY")
    assert upsert_ohlcv_bars(db_session, asset.id, "yfinance", []) == (0, 0)
    assert _count_ohlcv(db_session, asset.id) == 0


# ---------------------------------------------------------------------------
# sync_ohlcv task orchestration
# ---------------------------------------------------------------------------


def test_sync_ohlcv_success_writes_bars_and_returns_result(
    monkeypatch, db_session: Session
) -> None:
    asset = _make_asset(db_session, "FRA8TEST-SYNC")
    bars = [_bar("2024-01-02", "100", "99"), _bar("2024-01-03", "101", "100")]

    import worker.tasks.ohlcv as task_mod

    monkeypatch.setattr(task_mod, "fetch_ohlcv", lambda *a, **kw: bars)

    result = sync_ohlcv(str(asset.id), "2024-01-01", "2024-01-05", "yfinance")

    assert result["status"] == "success"
    assert result["inserted"] == 2
    assert result["updated"] == 0
    assert result["total_bars"] == 2
    assert result["asset_id"] == str(asset.id)
    # sync_ohlcv uses its own SessionLocal (same DB); roll back the fixture's
    # open txn so the next read sees the committed rows.
    db_session.rollback()
    assert _count_ohlcv(db_session, asset.id) == 2


def test_sync_ohlcv_unknown_asset_raises(monkeypatch) -> None:
    with pytest.raises(ValueError, match="not found"):
        sync_ohlcv(str(uuid.uuid4()), "2024-01-01", "2024-01-05", "yfinance")


def test_sync_ohlcv_unsupported_source_raises(monkeypatch, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA8TEST-SRC")
    with pytest.raises(ValueError, match="unsupported source"):
        sync_ohlcv(str(asset.id), "2024-01-01", "2024-01-05", "bloomberg")


def test_sync_ohlcv_fetch_failure_rolls_back(monkeypatch, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA8TEST-FAIL")

    def boom(*args: object, **kwargs: object) -> None:
        raise requests.exceptions.ConnectionError("persistent failure")

    import worker.tasks.ohlcv as task_mod

    monkeypatch.setattr(task_mod, "fetch_ohlcv", boom)

    with pytest.raises(requests.exceptions.ConnectionError):
        sync_ohlcv(str(asset.id), "2024-01-01", "2024-01-05", "yfinance")

    db_session.rollback()
    assert _count_ohlcv(db_session, asset.id) == 0


# ---------------------------------------------------------------------------
# RQ status mapping + sanitized error summary
# ---------------------------------------------------------------------------


def _fake_job(
    status: str,
    result: object = None,
    args: list | None = None,
    exc_info: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="job-x",
        result=result,
        args=args or [],
        exc_info=exc_info,
        is_failed=status == "failed",
        is_finished=status == "finished",
        is_started=status == "started",
        is_queued=status == "queued",
    )


def test_map_rq_status_lifecycle() -> None:
    assert map_rq_status(None) == "pending"
    assert map_rq_status(_fake_job("queued")) == "pending"
    assert map_rq_status(_fake_job("started")) == "running"
    assert map_rq_status(_fake_job("finished")) == "success"
    assert map_rq_status(_fake_job("failed")) == "failed"


def test_safe_error_summary_strips_traceback() -> None:
    exc_info = (
        "Traceback (most recent call last):\n"
        '  File "/secret/path/worker.py", line 42, in sync_ohlcv\n'
        "    raise ValueError(...)\n"
        "ValueError: asset deadbeef not found"
    )
    summary = safe_error_summary(_fake_job("failed", exc_info=exc_info))
    assert summary == {"type": "ValueError", "message": "asset deadbeef not found"}
    assert "Traceback" not in summary["message"]
    assert "/secret/" not in str(summary)


def test_safe_error_summary_none_when_not_failed() -> None:
    assert safe_error_summary(None) is None
    assert safe_error_summary(_fake_job("finished")) is None
    assert safe_error_summary(_fake_job("failed", exc_info=None)) is None


def test_parse_job_inputs_roundtrip() -> None:
    aid = uuid.uuid4()
    job = _fake_job("finished", args=[str(aid), "2024-01-01", "2024-01-05", "yfinance"])
    inputs = parse_job_inputs(job)
    assert inputs["asset_id"] == aid
    assert inputs["start"] == date(2024, 1, 1)
    assert inputs["end"] == date(2024, 1, 5)
    assert inputs["source"] == "yfinance"


def test_parse_job_inputs_malformed_returns_empty() -> None:
    job = _fake_job("finished", args=["not-a-uuid", "bad", "alsobad"])
    assert parse_job_inputs(job) == {}


# ---------------------------------------------------------------------------
# /sync API (input validation + job status polling)
# ---------------------------------------------------------------------------


class _FakeQueue:
    """In-memory RQ Queue stand-in: records enqueues and serves fetch_job."""

    def __init__(self) -> None:
        self.jobs: dict[str, SimpleNamespace] = {}
        self.enqueued: list[tuple] = []

    def enqueue(self, func_path: str, *args: object, **kwargs: object) -> SimpleNamespace:
        jid = f"job-{len(self.enqueued) + 1}"
        job = SimpleNamespace(
            id=jid,
            is_queued=True,
            is_started=False,
            is_finished=False,
            is_failed=False,
            args=list(args),
            result=None,
            exc_info=None,
        )
        self.jobs[jid] = job
        self.enqueued.append((func_path, args, kwargs))
        return job

    def fetch_job(self, job_id: str) -> SimpleNamespace | None:
        return self.jobs.get(job_id)


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    fake_queue = _FakeQueue()

    def _override_get_db() -> Iterator[Session]:
        try:
            yield db_session
        finally:
            # Fixture owns the session lifecycle; do not close here.
            pass

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_data_queue] = lambda: fake_queue
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _fake_queue_of() -> _FakeQueue:
    return app.dependency_overrides[get_data_queue]()


def test_post_sync_unknown_asset_returns_404(client: TestClient) -> None:
    resp = client.post(
        "/sync",
        json={"asset_id": str(uuid.uuid4()), "start": "2024-01-01", "end": "2024-01-05"},
    )
    assert resp.status_code == 404


def test_post_sync_start_after_end_returns_422(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA8TEST-V1")
    resp = client.post(
        "/sync",
        json={"asset_id": str(asset.id), "start": "2024-01-05", "end": "2024-01-01"},
    )
    assert resp.status_code == 422


def test_post_sync_bad_source_returns_422(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA8TEST-V2")
    resp = client.post(
        "/sync",
        json={
            "asset_id": str(asset.id),
            "start": "2024-01-01",
            "end": "2024-01-05",
            "source": "bloomberg",
        },
    )
    assert resp.status_code == 422


def test_post_sync_window_too_large_returns_422(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA8TEST-V3")
    resp = client.post(
        "/sync",
        json={"asset_id": str(asset.id), "start": "2010-01-01", "end": "2024-01-01"},
    )
    assert resp.status_code == 422


def test_post_sync_enqueues_and_returns_202(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA8TEST-ENQ")
    resp = client.post(
        "/sync",
        json={"asset_id": str(asset.id), "start": "2024-01-01", "end": "2024-01-05"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert body["job_id"]
    assert body["asset_id"] == str(asset.id)
    # fake queue captured the enqueue with string args + correct task path
    func_path, args, kwargs = _fake_queue_of().enqueued[0]
    assert func_path == "worker.tasks.ohlcv.sync_ohlcv"
    assert args[0] == str(asset.id)
    assert kwargs["job_timeout"] == 600
    assert kwargs["result_ttl"] == 86400


def test_get_sync_status_success_returns_counts(client: TestClient, db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA8TEST-GETOK")
    job = SimpleNamespace(
        id="job-done",
        is_queued=False,
        is_started=False,
        is_finished=True,
        is_failed=False,
        args=[str(asset.id), "2024-01-01", "2024-01-05", "yfinance"],
        result={"inserted": 5, "updated": 1, "status": "success"},
        exc_info=None,
    )
    _fake_queue_of().jobs["job-done"] = job

    resp = client.get("/sync/job-done")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["inserted"] == 5
    assert body["updated"] == 1
    assert body["asset_id"] == str(asset.id)
    assert body["error"] is None


def test_get_sync_status_failed_returns_sanitized_error(client: TestClient) -> None:
    job = SimpleNamespace(
        id="job-bad",
        is_queued=False,
        is_started=False,
        is_finished=False,
        is_failed=True,
        args=[str(uuid.uuid4()), "2024-01-01", "2024-01-05", "yfinance"],
        result=None,
        exc_info="Traceback ...\nValueError: asset not found",
    )
    _fake_queue_of().jobs["job-bad"] = job

    resp = client.get("/sync/job-bad")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error"] == {"type": "ValueError", "message": "asset not found"}
    assert body["inserted"] is None
    assert "Traceback" not in str(body)


def test_get_sync_status_unknown_job_returns_404(client: TestClient) -> None:
    resp = client.get("/sync/does-not-exist")
    assert resp.status_code == 404
