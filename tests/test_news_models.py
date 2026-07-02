"""ORM metadata + real-DB tests for news/sentiment storage (FRA-66).

Part 1 (metadata contract, no DB): mirrors ``test_factor_models.py`` — asserts
column names/types, the ``score``/``confidence`` ``Numeric(10,6)`` precision, FK
targets, unique-constraint names+columns, and index names+columns straight off
``__table__``.

Part 2 (real DB): mirrors ``test_backtest_models.py`` — uses the host Postgres
via ``SessionLocal`` with surgical cleanup scoped to the ``FRA66TEST`` prefix
(FK order: ``sentiment_scores`` → ``news_items`` → ``assets``).
``tests/conftest.py`` is left untouched to avoid merge conflicts with parallel
work.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.news import NewsItem, SentimentScore
from sqlalchemy import UniqueConstraint, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

PREFIX = "FRA66TEST"


# ---------------------------------------------------------------------------
# DB helpers + fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    """Delete only rows owned by this suite, respecting FK order."""
    asset_ids = "SELECT id FROM assets WHERE symbol LIKE :p"
    db.execute(
        text(f"DELETE FROM sentiment_scores WHERE asset_id IN ({asset_ids})"),
        {"p": f"{PREFIX}%"},
    )
    db.execute(
        text(f"DELETE FROM news_items WHERE asset_id IN ({asset_ids})"),
        {"p": f"{PREFIX}%"},
    )
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


def _hash(headline: str) -> str:
    return hashlib.sha256(headline.encode("utf-8")).hexdigest()


def _news_values(
    asset: Asset, published_at: datetime, headline: str, **extra: Any
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "asset_id": asset.id,
        "source": "reuters",
        "published_at": published_at,
        "headline": headline,
        "headline_hash": _hash(headline),
        "raw_payload": {"fetched_at": "2026-06-29T14:00:00Z", "meta": {"lang": "en"}},
    }
    values.update(extra)
    return values


# ---------------------------------------------------------------------------
# Part 1 — metadata contract (no DB)
# ---------------------------------------------------------------------------


def test_news_items_table_contract() -> None:
    table = NewsItem.__table__

    assert table.name == "news_items"
    assert [c.name for c in table.primary_key.columns] == ["id"]
    assert table.c.asset_id.foreign_keys  # FK -> assets
    assert table.c.source.type.python_type is str
    assert table.c.published_at.type.python_type is datetime
    assert table.c.headline.type.python_type is str
    assert table.c.headline_hash.type.python_type is str
    assert table.c.summary.nullable is True
    assert table.c.url.nullable is True
    assert table.c.provider_id.nullable is True
    assert table.c.raw_payload.nullable is False
    assert table.c.created_at.server_default is not None

    uq = {
        const.name: [c.name for c in const.columns]
        for const in table.constraints
        if isinstance(const, UniqueConstraint)
    }
    assert uq["uq_news_items_asset_source_time_hash"] == [
        "asset_id",
        "source",
        "published_at",
        "headline_hash",
    ]

    idx = {i.name: [c.name for c in i.columns] for i in table.indexes}
    assert idx["ix_news_items_asset_id_published_at"] == ["asset_id", "published_at"]
    assert idx["ix_news_items_source_published_at"] == ["source", "published_at"]


def test_sentiment_scores_table_contract() -> None:
    table = SentimentScore.__table__

    assert table.name == "sentiment_scores"
    assert [c.name for c in table.primary_key.columns] == ["id"]
    assert {fk.column.table.name for fk in table.c.news_item_id.foreign_keys} == {"news_items"}
    assert {fk.column.table.name for fk in table.c.asset_id.foreign_keys} == {"assets"}
    assert table.c.model_name.type.python_type is str
    assert table.c.label.type.python_type is str
    assert table.c.score.type.precision == 10
    assert table.c.score.type.scale == 6
    assert table.c.score.nullable is False
    assert table.c.confidence.type.precision == 10
    assert table.c.confidence.type.scale == 6
    assert table.c.confidence.nullable is True
    assert table.c.raw_response.nullable is True
    assert table.c.params.nullable is False
    assert table.c.params.server_default is not None  # '{}'::jsonb

    uq = {
        const.name: [c.name for c in const.columns]
        for const in table.constraints
        if isinstance(const, UniqueConstraint)
    }
    assert uq["uq_sentiment_scores_news_model"] == ["news_item_id", "model_name"]

    idx = {i.name: [c.name for c in i.columns] for i in table.indexes}
    assert idx["ix_sentiment_scores_model_name_published_at"] == [
        "model_name",
        "published_at",
    ]


# ---------------------------------------------------------------------------
# Part 2 — real DB
# ---------------------------------------------------------------------------


def test_news_item_defaults_and_raw_payload_roundtrip(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA66TEST-N1")
    ts = datetime(2026, 6, 29, 13, 30, tzinfo=UTC)
    news = NewsItem(**_news_values(asset, ts, "AAPL surges on Q3 earnings beat"))
    db_session.add(news)
    db_session.commit()
    db_session.refresh(news)

    assert news.id is not None  # server gen_random_uuid()
    assert news.created_at is not None  # server now()
    payload = news.raw_payload
    assert payload["fetched_at"] == "2026-06-29T14:00:00Z"
    assert payload["meta"] == {"lang": "en"}  # JSONB nests a dict unchanged


def test_sentiment_score_params_roundtrip_and_nullables(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA66TEST-S1")
    ts = datetime(2026, 6, 29, 13, 30, tzinfo=UTC)
    news = NewsItem(**_news_values(asset, ts, "AAPL surges on Q3 earnings beat"))
    db_session.add(news)
    db_session.commit()
    db_session.refresh(news)

    params = {"model_name": "gpt-4o", "prompt_version": "v1", "temperature": 0.0}
    score = SentimentScore(
        news_item_id=news.id,
        asset_id=asset.id,
        published_at=ts,
        model_name="gpt-4o",
        label="positive",
        score=Decimal("0.834561"),
        confidence=None,
        raw_response=None,
        params=params,
    )
    db_session.add(score)
    db_session.commit()
    db_session.refresh(score)

    assert score.id is not None
    assert score.created_at is not None
    assert score.score == Decimal("0.834561")  # Numeric(10,6) preserves scale
    assert score.confidence is None
    assert score.raw_response is None
    assert score.params == params
    # FRA-65 reproducibility metadata lands in params (JSONB)
    assert score.params["prompt_version"] == "v1"


def test_news_item_unique_constraint_dedup(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA66TEST-NQ")
    ts = datetime(2026, 6, 29, 13, 30, tzinfo=UTC)

    # Same asset/source/time but distinct headlines → distinct hashes → coexist.
    db_session.add(NewsItem(**_news_values(asset, ts, "AAPL surges on earnings")))
    db_session.add(NewsItem(**_news_values(asset, ts, "AAPL slides after downgrade")))
    db_session.commit()
    assert len(db_session.scalars(select(NewsItem).where(NewsItem.asset_id == asset.id)).all()) == 2

    # Same (asset, source, time, headline_hash) → violates the unique constraint.
    # Core insert bypasses the session identity map (an ORM add would raise a
    # noisy SAWarning before the IntegrityError).
    with pytest.raises(IntegrityError):
        db_session.execute(
            insert(NewsItem).values(**_news_values(asset, ts, "AAPL surges on earnings"))
        )
        db_session.commit()
    db_session.rollback()


def test_sentiment_score_unique_constraint(db_session: Session) -> None:
    asset = _make_asset(db_session, "FRA66TEST-SQ")
    ts = datetime(2026, 6, 29, 13, 30, tzinfo=UTC)
    news = NewsItem(**_news_values(asset, ts, "AAPL surges on earnings"))
    db_session.add(news)
    db_session.commit()
    db_session.refresh(news)

    base: dict[str, Any] = {
        "news_item_id": news.id,
        "asset_id": asset.id,
        "published_at": ts,
        "label": "positive",
        "score": Decimal("0.5"),
        "params": {"prompt_version": "v1"},
    }
    db_session.add(SentimentScore(model_name="gpt-4o", **base))
    db_session.commit()

    # Same (news_item_id, model_name) → violates the unique constraint.
    with pytest.raises(IntegrityError):
        db_session.execute(insert(SentimentScore).values(model_name="gpt-4o", **base))
        db_session.commit()
    db_session.rollback()
