"""News ingestion + worker task tests (FRA-67).

Covers :func:`upsert_news_items` (idempotent write, dedup, overwrite),
:func:`sync_news` (preflight failures, success path, idempotency, no-data), and
the ``worker.tasks.sentiment.sync_news`` RQ entry point.

Mirrors the per-file fixture pattern of ``test_news_models.py`` /
``test_ohlcv_ingestion.py``: a surgical ``db_session`` fixture cleans only
``FRA67TEST``-prefixed rows (FK order: ``news_items`` → ``assets``) and the root
``conftest.py`` is left untouched to avoid merge conflicts with parallel work.

The service-layer ``sync_news`` opens its own ``SessionLocal()`` (like
``sync_ohlcv``); tests inject a stub provider by monkeypatching
``get_news_provider`` on the ingest module so the universe→symbol→UUID mapping,
preflight, and upsert run against the real DB with the fixture provider's
deterministic samples.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.news import NewsItem as NewsItemModel
from app.services.sentiment.ingest import sync_news, upsert_news_items
from app.services.sentiment.providers.fixture import FixtureNewsProvider
from app.services.sentiment.types import NewsItem
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from worker.tasks.sentiment import sync_news as sync_news_task

PREFIX = "FRA67TEST"


# ---------------------------------------------------------------------------
# DB helpers + fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    """Delete only rows owned by this suite, respecting FK order."""
    asset_ids = "SELECT id FROM assets WHERE symbol LIKE :p"
    db.execute(text(f"DELETE FROM news_items WHERE asset_id IN ({asset_ids})"), {"p": f"{PREFIX}%"})
    db.execute(text("DELETE FROM assets WHERE symbol LIKE :p"), {"p": f"{PREFIX}%"})
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


def _make_asset(db: Session, symbol: str, data_source: str = "yfinance") -> Asset:
    asset = Asset(
        symbol=symbol,
        name=f"Test {symbol}",
        exchange="NASDAQ",
        asset_type="stock",
        currency="USD",
        data_source=data_source,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _hash(headline: str) -> str:
    return hashlib.sha256(headline.encode("utf-8")).hexdigest()


def _row(asset: Asset, published_at: datetime, headline: str, **extra: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "asset_id": asset.id,
        "source": "fixture",
        "published_at": published_at,
        "headline": headline,
        "headline_hash": _hash(headline),
        "raw_payload": {"provider": "fixture", "fetched_at": "2024-06-04T00:00:00+00:00"},
    }
    values.update(extra)
    return values


def _stub_provider(symbol: str, headlines: list[tuple[datetime, str]]) -> FixtureNewsProvider:
    """Build a fixture provider whose samples target one test symbol."""
    samples = [
        NewsItem(
            asset_id=symbol,
            published_at=when,
            source="fixture",
            headline=headline,
        )
        for when, headline in headlines
    ]
    return FixtureNewsProvider(samples=samples)


def _patch_provider(monkeypatch: pytest.MonkeyPatch, provider: FixtureNewsProvider) -> None:
    import app.services.sentiment.ingest as ingest_mod

    monkeypatch.setattr(ingest_mod, "get_news_provider", lambda _key: provider)


# ---------------------------------------------------------------------------
# upsert_news_items — idempotent write (direct, injected session)
# ---------------------------------------------------------------------------


def test_upsert_news_items_empty_returns_zero(db_session: Session) -> None:
    assert upsert_news_items(db_session, []) == (0, 0)


def test_upsert_news_items_inserts_new_rows(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA67TEST-UP1")
    ts = datetime(2024, 6, 4, 14, 0, tzinfo=UTC)
    rows = [
        _row(asset, ts, "headline A"),
        _row(asset, ts, "headline B"),
    ]
    inserted, updated = upsert_news_items(db_session, rows)
    db_session.commit()
    assert inserted == 2
    assert updated == 0
    assert (
        len(
            db_session.scalars(
                select(NewsItemModel).where(NewsItemModel.asset_id == asset.id)
            ).all()
        )
        == 2
    )


def test_upsert_news_items_is_idempotent(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA67TEST-UP2")
    ts = datetime(2024, 6, 4, 14, 0, tzinfo=UTC)
    rows = [_row(asset, ts, "headline A"), _row(asset, ts, "headline B")]

    upsert_news_items(db_session, rows)
    db_session.commit()

    inserted2, updated2 = upsert_news_items(db_session, rows)
    db_session.commit()

    assert inserted2 == 0
    assert updated2 == 2
    # No duplicate rows — total unchanged after the second call.
    total = len(
        db_session.scalars(select(NewsItemModel).where(NewsItemModel.asset_id == asset.id)).all()
    )
    assert total == 2


def test_upsert_news_items_distinct_headlines_coexist(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA67TEST-UP3")
    ts = datetime(2024, 6, 4, 14, 0, tzinfo=UTC)
    upsert_news_items(db_session, [_row(asset, ts, "AAA"), _row(asset, ts, "BBB")])
    db_session.commit()
    headlines = {
        r.headline
        for r in db_session.scalars(
            select(NewsItemModel).where(NewsItemModel.asset_id == asset.id)
        ).all()
    }
    assert headlines == {"AAA", "BBB"}


def test_upsert_news_items_overwrites_same_conflict_key(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA67TEST-UP4")
    ts = datetime(2024, 6, 4, 14, 0, tzinfo=UTC)
    # First write: summary = None.
    upsert_news_items(db_session, [_row(asset, ts, "same headline", summary=None)])
    db_session.commit()
    # Second write: same conflict key, revised summary + url.
    upsert_news_items(
        db_session,
        [_row(asset, ts, "same headline", summary="revised", url="https://x")],
    )
    db_session.commit()

    rows = db_session.scalars(select(NewsItemModel).where(NewsItemModel.asset_id == asset.id)).all()
    assert len(rows) == 1  # still one row (overwritten, not duplicated)
    assert rows[0].summary == "revised"
    assert rows[0].url == "https://x"


def test_upsert_news_items_persists_headline_hash_and_raw_payload(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA67TEST-UP5")
    ts = datetime(2024, 6, 4, 14, 0, tzinfo=UTC)
    upsert_news_items(db_session, [_row(asset, ts, "hash me")])
    db_session.commit()
    row = db_session.scalars(select(NewsItemModel).where(NewsItemModel.asset_id == asset.id)).one()
    assert row.headline_hash == _hash("hash me")
    assert row.raw_payload["provider"] == "fixture"


# ---------------------------------------------------------------------------
# sync_news — preflight failures
# ---------------------------------------------------------------------------


def test_sync_news_invalid_window_start_after_end_raises(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA67TEST-PF1")
    with pytest.raises(ValueError, match="invalid window"):
        sync_news(
            [asset.id],
            datetime(2024, 6, 5, tzinfo=UTC),
            datetime(2024, 6, 5, tzinfo=UTC),
        )


def test_sync_news_window_too_large_raises(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA67TEST-PF2")
    with pytest.raises(ValueError, match="window too large"):
        sync_news(
            [asset.id],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 3, 15, tzinfo=UTC),  # 74 days > 30 default
        )


def test_sync_news_unknown_provider_raises(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA67TEST-PF3")
    with pytest.raises(ValueError, match="unsupported news provider"):
        sync_news(
            [asset.id],
            datetime(2024, 6, 3, tzinfo=UTC),
            datetime(2024, 6, 5, tzinfo=UTC),
            provider_key="bloomberg",
        )


def test_sync_news_missing_asset_raises(db_session: Session) -> None:
    # An asset_id that does not exist in the DB.
    fake_id = "00000000-0000-0000-0000-000000000001"
    with pytest.raises(ValueError, match="assets not found"):
        sync_news(
            [__import__("uuid").UUID(fake_id)],
            datetime(2024, 6, 3, tzinfo=UTC),
            datetime(2024, 6, 5, tzinfo=UTC),
            provider_key="fixture",
        )


# ---------------------------------------------------------------------------
# sync_news — success path + idempotency + no-data
# ---------------------------------------------------------------------------


def test_sync_news_writes_items_and_returns_success(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db_session, "FRA67TEST-OK1")
    in_window = datetime(2024, 6, 4, 14, 0, tzinfo=UTC)
    _patch_provider(
        monkeypatch,
        _stub_provider(
            "FRA67TEST-OK1",
            [(in_window, "ok headline 1"), (in_window, "ok headline 2")],
        ),
    )

    result = sync_news(
        [asset.id],
        datetime(2024, 6, 3, tzinfo=UTC),
        datetime(2024, 6, 5, tzinfo=UTC),
        provider_key="fixture",
    )

    assert result["status"] == "success"
    assert result["fetched"] == 2
    assert result["inserted"] == 2
    assert result["updated"] == 0
    assert result["provider"] == "fixture"
    assert result["warning"] is None
    rows = db_session.scalars(select(NewsItemModel).where(NewsItemModel.asset_id == asset.id)).all()
    assert len(rows) == 2
    assert all(r.source == "fixture" for r in rows)
    assert all(r.headline_hash == _hash(r.headline) for r in rows)


def test_sync_news_is_idempotent_on_repeat(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db_session, "FRA67TEST-OK2")
    in_window = datetime(2024, 6, 4, 14, 0, tzinfo=UTC)
    _patch_provider(
        monkeypatch,
        _stub_provider("FRA67TEST-OK2", [(in_window, "repeat headline")]),
    )

    first = sync_news(
        [asset.id], datetime(2024, 6, 3, tzinfo=UTC), datetime(2024, 6, 5, tzinfo=UTC)
    )
    second = sync_news(
        [asset.id], datetime(2024, 6, 3, tzinfo=UTC), datetime(2024, 6, 5, tzinfo=UTC)
    )

    assert first["inserted"] == 1
    assert second["inserted"] == 0
    assert second["updated"] == 1
    total = len(
        db_session.scalars(select(NewsItemModel).where(NewsItemModel.asset_id == asset.id)).all()
    )
    assert total == 1  # no duplicate


def test_sync_news_no_data_returns_success_no_data(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db_session, "FRA67TEST-OK3")
    # Sample is at 2024-06-04; window [2024-06-06, 2024-06-10) excludes it.
    _patch_provider(
        monkeypatch,
        _stub_provider("FRA67TEST-OK3", [(datetime(2024, 6, 4, 14, 0, tzinfo=UTC), "excluded")]),
    )
    result = sync_news(
        [asset.id],
        datetime(2024, 6, 6, tzinfo=UTC),
        datetime(2024, 6, 10, tzinfo=UTC),
        provider_key="fixture",
    )
    assert result["status"] == "success_no_data"
    assert result["fetched"] == 0
    assert result["warning"] is not None
    assert (
        len(
            db_session.scalars(
                select(NewsItemModel).where(NewsItemModel.asset_id == asset.id)
            ).all()
        )
        == 0
    )


def test_sync_news_preserves_raw_payload_from_provider_params(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db_session, "FRA67TEST-OK4")
    in_window = datetime(2024, 6, 4, 14, 0, tzinfo=UTC)
    samples = [
        NewsItem(
            asset_id="FRA67TEST-OK4",
            published_at=in_window,
            source="yfinance",
            headline="with raw",
            params={"publisher": "Reuters", "raw": {"title": "with raw", "x": 1}},
        )
    ]
    _patch_provider(monkeypatch, FixtureNewsProvider(samples=samples))

    sync_news(
        [asset.id],
        datetime(2024, 6, 3, tzinfo=UTC),
        datetime(2024, 6, 5, tzinfo=UTC),
        provider_key="yfinance",
    )
    row = db_session.scalars(select(NewsItemModel).where(NewsItemModel.asset_id == asset.id)).one()
    assert row.raw_payload["provider"] == "yfinance"
    assert row.raw_payload["raw"] == {"title": "with raw", "x": 1}


# ---------------------------------------------------------------------------
# worker.tasks.sentiment.sync_news — RQ entry point
# ---------------------------------------------------------------------------


def test_task_sync_news_success(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    asset = _make_asset(db_session, "FRA67TEST-T1")
    in_window = datetime(2024, 6, 4, 14, 0, tzinfo=UTC)
    _patch_provider(monkeypatch, _stub_provider("FRA67TEST-T1", [(in_window, "task headline")]))

    result = sync_news_task(
        [str(asset.id)],
        datetime(2024, 6, 3, tzinfo=UTC).isoformat(),
        datetime(2024, 6, 5, tzinfo=UTC).isoformat(),
        provider="fixture",
    )
    assert result["status"] == "success"
    assert result["inserted"] == 1
    rows = db_session.scalars(select(NewsItemModel).where(NewsItemModel.asset_id == asset.id)).all()
    assert len(rows) == 1
    assert rows[0].headline == "task headline"


def test_task_sync_news_missing_asset_raises() -> None:
    fake_id = "00000000-0000-0000-0000-000000000002"
    with pytest.raises(ValueError, match="assets not found"):
        sync_news_task(
            [fake_id],
            datetime(2024, 6, 3, tzinfo=UTC).isoformat(),
            datetime(2024, 6, 5, tzinfo=UTC).isoformat(),
            provider="fixture",
        )
