"""Sentiment daily factor + service tests (FRA-69).

Covers :class:`DailySentimentFactor.compute` (pure unit, no DB), the summary
builder, and the DB-backed service layer (:func:`read_sentiment_scores`,
:func:`compute_sentiment_factor`, :func:`compute_and_store_sentiment_factor`).

Anti-cheat properties verified:
* published_at maps to a signal_date **at or after** publication — never earlier.
* news published during trading hours (after midnight) maps to the **next** day.
* missing coverage stays ``NaN`` — no forward-fill across trading dates.
* scores past the last calendar day are dropped (their signal is unusable).

DB integration follows the per-file fixture pattern (PREFIX ``FRA69TEST``,
FK cleanup order ``factor_values`` → ``sentiment_scores`` → ``news_items`` →
``assets``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.factor import FactorValue
from app.models.news import NewsItem as NewsItemModel
from app.models.news import SentimentScore as SentimentScoreModel
from app.services.sentiment.factor import DailySentimentFactor, build_sentiment_summaries
from app.services.sentiment.service import (
    SENTIMENT_FACTOR_NAME,
    SENTIMENT_NEWS_COUNT_FACTOR_NAME,
    compute_and_store_sentiment_factor,
    compute_sentiment_factor,
    get_sentiment_summaries,
    read_sentiment_scores,
)
from app.services.sentiment.types import SentimentLabel, SentimentScore
from sqlalchemy import select, text
from sqlalchemy.orm import Session

PREFIX = "FRA69TEST"

# June 2024 trading days (Mon–Fri, US calendar).
_CAL = pd.DatetimeIndex(
    [
        pd.Timestamp(d, tz="UTC")
        for d in [
            date(2024, 6, 3),  # Mon
            date(2024, 6, 4),  # Tue
            date(2024, 6, 5),  # Wed
            date(2024, 6, 6),  # Thu
            date(2024, 6, 7),  # Fri
        ]
    ]
)


# ---------------------------------------------------------------------------
# helpers — no-DB unit fixtures
# ---------------------------------------------------------------------------


def _score(
    asset_id: str,
    published_at: datetime,
    score_val: float = 0.6,
    label: SentimentLabel = "positive",
    confidence: float = 0.7,
    model_name: str = "fixture-model",
) -> SentimentScore:
    return SentimentScore(
        asset_id=asset_id,
        published_at=published_at,
        source="fixture",
        headline="test headline",
        model_name=model_name,
        prompt_version="sentiment-v1",
        label=label,
        score=score_val,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# DailySentimentFactor.compute — pure unit tests
# ---------------------------------------------------------------------------


class TestDailySentimentFactorCompute:
    def test_empty_scores_returns_nan_frame(self) -> None:
        f = DailySentimentFactor()
        result = f.compute([], _CAL)
        assert result.shape == (len(_CAL), 0)
        assert result.index.equals(_CAL)

    def test_midnight_publication_maps_to_same_day(self) -> None:
        f = DailySentimentFactor()
        s = _score("A1", datetime(2024, 6, 3, 0, 0, tzinfo=UTC), score_val=0.5)
        result = f.compute([s], _CAL)
        assert result.loc[pd.Timestamp(2024, 6, 3, tz="UTC"), "A1"] == pytest.approx(0.5)
        # Other days should be NaN for this asset.
        assert pd.isna(result.loc[pd.Timestamp(2024, 6, 4, tz="UTC"), "A1"])

    def test_intraday_publication_maps_to_next_day(self) -> None:
        """News at 13:30 UTC on Mon maps to Tue (anti-cheat: decision is at midnight)."""
        f = DailySentimentFactor()
        s = _score("A1", datetime(2024, 6, 3, 13, 30, tzinfo=UTC), score_val=0.5)
        result = f.compute([s], _CAL)
        assert pd.isna(result.loc[pd.Timestamp(2024, 6, 3, tz="UTC"), "A1"])
        assert result.loc[pd.Timestamp(2024, 6, 4, tz="UTC"), "A1"] == pytest.approx(0.5)

    def test_multiple_scores_same_day_averaged(self) -> None:
        f = DailySentimentFactor()
        scores = [
            _score("A1", datetime(2024, 6, 3, 0, 0, tzinfo=UTC), score_val=0.6),
            _score("A1", datetime(2024, 6, 3, 0, 0, tzinfo=UTC), score_val=-0.4),
            _score("A1", datetime(2024, 6, 3, 0, 0, tzinfo=UTC), score_val=0.9),
        ]
        result = f.compute(scores, _CAL)
        expected = (0.6 + (-0.4) + 0.9) / 3
        assert result.loc[pd.Timestamp(2024, 6, 3, tz="UTC"), "A1"] == pytest.approx(expected)

    def test_no_forward_fill(self) -> None:
        """Day with news → value; next day without news → NaN (not carried over)."""
        f = DailySentimentFactor()
        s = _score("A1", datetime(2024, 6, 3, 0, 0, tzinfo=UTC), score_val=0.8)
        result = f.compute([s], _CAL)
        assert result.loc[pd.Timestamp(2024, 6, 3, tz="UTC"), "A1"] == pytest.approx(0.8)
        assert pd.isna(result.loc[pd.Timestamp(2024, 6, 4, tz="UTC"), "A1"])
        assert pd.isna(result.loc[pd.Timestamp(2024, 6, 5, tz="UTC"), "A1"])

    def test_score_past_calendar_end_dropped(self) -> None:
        f = DailySentimentFactor()
        s = _score("A1", datetime(2024, 6, 7, 15, 0, tzinfo=UTC), score_val=0.5)
        result = f.compute([s], _CAL)
        # Published Fri afternoon → maps to Mon Jun 10, which is past calendar.
        assert "A1" not in result.columns or result["A1"].isna().all()

    def test_multiple_assets(self) -> None:
        f = DailySentimentFactor()
        scores = [
            _score("A1", datetime(2024, 6, 3, 0, 0, tzinfo=UTC), score_val=0.3),
            _score("A2", datetime(2024, 6, 4, 0, 0, tzinfo=UTC), score_val=-0.5),
        ]
        result = f.compute(scores, _CAL)
        assert set(result.columns) == {"A1", "A2"}
        assert result.loc[pd.Timestamp(2024, 6, 3, tz="UTC"), "A1"] == pytest.approx(0.3)
        assert result.loc[pd.Timestamp(2024, 6, 4, tz="UTC"), "A2"] == pytest.approx(-0.5)

    def test_naive_datetime_treated_as_utc(self) -> None:
        f = DailySentimentFactor()
        s = _score("A1", datetime(2024, 6, 3, 0, 0), score_val=0.5)  # no tzinfo
        result = f.compute([s], _CAL)
        assert result.loc[pd.Timestamp(2024, 6, 3, tz="UTC"), "A1"] == pytest.approx(0.5)

    def test_empty_calendar_raises(self) -> None:
        f = DailySentimentFactor()
        with pytest.raises(ValueError, match="trading_calendar must not be empty"):
            f.compute([], pd.DatetimeIndex([]))

    def test_modifying_future_news_does_not_affect_past(self) -> None:
        """Anti-cheat: adding news for day T+1 must not change day T's factor."""
        f = DailySentimentFactor()
        past_only = [_score("A1", datetime(2024, 6, 3, 0, 0, tzinfo=UTC), score_val=0.5)]
        result_before = f.compute(past_only, _CAL)

        past_plus_future = past_only + [
            _score("A1", datetime(2024, 6, 6, 0, 0, tzinfo=UTC), score_val=0.9),
        ]
        result_after = f.compute(past_plus_future, _CAL)

        # Day 1 value unchanged.
        d1 = pd.Timestamp(2024, 6, 3, tz="UTC")
        assert result_before.loc[d1, "A1"] == result_after.loc[d1, "A1"]


# ---------------------------------------------------------------------------
# build_sentiment_summaries — pure unit tests
# ---------------------------------------------------------------------------


class TestBuildSentimentSummaries:
    def test_summary_fields(self) -> None:
        scores = [
            _score("A1", datetime(2024, 6, 3, 0, 0, tzinfo=UTC), score_val=0.6, label="positive"),
            _score("A1", datetime(2024, 6, 3, 0, 0, tzinfo=UTC), score_val=-0.3, label="negative"),
        ]
        summaries = build_sentiment_summaries(
            scores, _CAL, model_name="fixture-model", prompt_version="sentiment-v1"
        )
        assert len(summaries) == 1
        s = summaries[0]
        assert s.asset_id == "A1"
        assert s.signal_date == pd.Timestamp(2024, 6, 3, tz="UTC")
        assert s.news_count == 2
        assert s.score == pytest.approx((0.6 + (-0.3)) / 2)
        assert s.label_counts["positive"] == 1
        assert s.label_counts["negative"] == 1
        assert s.model_name == "fixture-model"
        assert s.prompt_version == "sentiment-v1"

    def test_empty_scores_returns_empty(self) -> None:
        assert build_sentiment_summaries([], _CAL, model_name="m", prompt_version="v") == []


# ---------------------------------------------------------------------------
# DB helpers + fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    asset_ids = "SELECT id FROM assets WHERE symbol LIKE :p"
    db.execute(
        text(f"DELETE FROM factor_values WHERE asset_id IN ({asset_ids})"), {"p": f"{PREFIX}%"}
    )
    db.execute(
        text(f"DELETE FROM sentiment_scores WHERE asset_id IN ({asset_ids})"),
        {"p": f"{PREFIX}%"},
    )
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


def _hash(headline: str) -> str:
    return hashlib.sha256(headline.encode("utf-8")).hexdigest()


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


def _make_news(
    db: Session,
    asset: Asset,
    headline: str,
    published_at: datetime,
    source: str = "fixture",
) -> NewsItemModel:
    news = NewsItemModel(
        asset_id=asset.id,
        source=source,
        published_at=published_at,
        headline=headline,
        headline_hash=_hash(headline),
        raw_payload={"provider": "fixture"},
    )
    db.add(news)
    db.commit()
    db.refresh(news)
    return news


def _make_score(
    db: Session,
    news: NewsItemModel,
    asset: Asset,
    published_at: datetime,
    label: str = "positive",
    score_val: float = 0.6,
    model_name: str = "fixture-model",
) -> SentimentScoreModel:
    row = SentimentScoreModel(
        news_item_id=news.id,
        asset_id=asset.id,
        published_at=published_at,
        model_name=model_name,
        label=label,
        score=Decimal(str(score_val)),
        confidence=Decimal("0.7"),
        raw_response={"classifier": "fixture"},
        params={"prompt_version": "sentiment-v1", "temperature": 0.0},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# read_sentiment_scores — DB
# ---------------------------------------------------------------------------


class TestReadSentimentScores:
    def test_reads_joined_fields(self, db_session: Session) -> None:
        asset = _make_asset(db_session, "FRA69TEST-R1")
        news = _make_news(db_session, asset, "surge", datetime(2024, 6, 3, 0, 0, tzinfo=UTC))
        _make_score(db_session, news, asset, news.published_at, label="positive", score_val=0.6)

        scores = read_sentiment_scores(
            db_session,
            asset_ids=[asset.id],
            start=date(2024, 6, 3),
            end=date(2024, 6, 7),
            model_name="fixture-model",
        )
        assert len(scores) == 1
        s = scores[0]
        assert s.asset_id == str(asset.id)
        assert s.headline == "surge"
        assert s.source == "fixture"
        assert s.label == "positive"
        assert s.score == pytest.approx(0.6)
        assert s.prompt_version == "sentiment-v1"

    def test_lookback_captures_overnight_news(self, db_session: Session) -> None:
        """News published the day before the window should be readable."""
        asset = _make_asset(db_session, "FRA69TEST-R2")
        # Published on Sun Jun 2 → maps to Mon Jun 3.
        news = _make_news(
            db_session, asset, "weekend news", datetime(2024, 6, 2, 12, 0, tzinfo=UTC)
        )
        _make_score(db_session, news, asset, news.published_at)

        scores = read_sentiment_scores(
            db_session,
            asset_ids=[asset.id],
            start=date(2024, 6, 3),
            end=date(2024, 6, 7),
            model_name="fixture-model",
        )
        assert len(scores) == 1

    def test_filters_by_model_name(self, db_session: Session) -> None:
        asset = _make_asset(db_session, "FRA69TEST-R3")
        news = _make_news(db_session, asset, "surge", datetime(2024, 6, 3, 0, 0, tzinfo=UTC))
        _make_score(db_session, news, asset, news.published_at, model_name="fixture-model")
        _make_score(db_session, news, asset, news.published_at, model_name="other-model")

        scores = read_sentiment_scores(
            db_session,
            asset_ids=[asset.id],
            start=date(2024, 6, 3),
            end=date(2024, 6, 7),
            model_name="fixture-model",
        )
        assert len(scores) == 1
        assert scores[0].model_name == "fixture-model"


# ---------------------------------------------------------------------------
# compute_sentiment_factor — DB
# ---------------------------------------------------------------------------


class TestComputeSentimentFactor:
    def test_returns_wide_frame(self, db_session: Session) -> None:
        asset = _make_asset(db_session, "FRA69TEST-C1")
        # Midnight publication → maps to same day.
        news = _make_news(db_session, asset, "surge", datetime(2024, 6, 3, 0, 0, tzinfo=UTC))
        _make_score(db_session, news, asset, news.published_at, score_val=0.6)

        frame = compute_sentiment_factor(
            db_session,
            asset_ids=[asset.id],
            start=date(2024, 6, 3),
            end=date(2024, 6, 7),
            model_name="fixture-model",
        )
        assert str(asset.id) in frame.columns
        d1 = pd.Timestamp(2024, 6, 3, tz="UTC")
        assert frame.loc[d1, str(asset.id)] == pytest.approx(0.6)
        # Day 2 should be NaN (no forward-fill).
        d2 = pd.Timestamp(2024, 6, 4, tz="UTC")
        assert pd.isna(frame.loc[d2, str(asset.id)])

    def test_intraday_maps_to_next_day(self, db_session: Session) -> None:
        asset = _make_asset(db_session, "FRA69TEST-C2")
        # 13:30 UTC on Mon → maps to Tue.
        news = _make_news(db_session, asset, "intraday", datetime(2024, 6, 3, 13, 30, tzinfo=UTC))
        _make_score(db_session, news, asset, news.published_at, score_val=-0.3, label="negative")

        frame = compute_sentiment_factor(
            db_session,
            asset_ids=[asset.id],
            start=date(2024, 6, 3),
            end=date(2024, 6, 7),
            model_name="fixture-model",
        )
        d1 = pd.Timestamp(2024, 6, 3, tz="UTC")
        d2 = pd.Timestamp(2024, 6, 4, tz="UTC")
        assert pd.isna(frame.loc[d1, str(asset.id)])
        assert frame.loc[d2, str(asset.id)] == pytest.approx(-0.3)

    def test_empty_universe_raises(self, db_session: Session) -> None:
        with pytest.raises(ValueError, match="asset_ids must contain at least one"):
            compute_sentiment_factor(
                db_session,
                asset_ids=[],
                start=date(2024, 6, 3),
                end=date(2024, 6, 7),
                model_name="fixture-model",
            )


# ---------------------------------------------------------------------------
# compute_and_store_sentiment_factor — DB persistence
# ---------------------------------------------------------------------------


class TestComputeAndStoreSentimentFactor:
    def test_persists_to_factor_values(self, db_session: Session) -> None:
        asset = _make_asset(db_session, "FRA69TEST-S1")
        news = _make_news(db_session, asset, "surge", datetime(2024, 6, 3, 0, 0, tzinfo=UTC))
        _make_score(db_session, news, asset, news.published_at, score_val=0.6)

        result = compute_and_store_sentiment_factor(
            db_session,
            universe=[asset.id],
            start=date(2024, 6, 3),
            end=date(2024, 6, 7),
            model_name="fixture-model",
        )
        assert result["status"] == "success"
        assert result["rows_written"] > 0

        # Verify factor_values has the sentiment_score factor.
        fv_rows = db_session.scalars(
            select(FactorValue).where(
                FactorValue.asset_id == asset.id,
                FactorValue.factor_name == SENTIMENT_FACTOR_NAME,
                FactorValue.source == "fixture-model",
            )
        ).all()
        assert len(fv_rows) >= 1
        d1 = datetime(2024, 6, 3, 0, 0, tzinfo=UTC)
        matching = [r for r in fv_rows if r.time == d1]
        assert len(matching) == 1
        assert float(matching[0].value) == pytest.approx(0.6)

    def test_persists_news_count_factor(self, db_session: Session) -> None:
        asset = _make_asset(db_session, "FRA69TEST-S2")
        # Two news items on same day.
        n1 = _make_news(db_session, asset, "surge", datetime(2024, 6, 3, 0, 0, tzinfo=UTC))
        n2 = _make_news(db_session, asset, "rally", datetime(2024, 6, 3, 0, 0, tzinfo=UTC))
        _make_score(db_session, n1, asset, n1.published_at, score_val=0.6)
        _make_score(db_session, n2, asset, n2.published_at, score_val=0.4)

        compute_and_store_sentiment_factor(
            db_session,
            universe=[asset.id],
            start=date(2024, 6, 3),
            end=date(2024, 6, 7),
            model_name="fixture-model",
        )

        count_rows = db_session.scalars(
            select(FactorValue).where(
                FactorValue.asset_id == asset.id,
                FactorValue.factor_name == SENTIMENT_NEWS_COUNT_FACTOR_NAME,
            )
        ).all()
        d1 = datetime(2024, 6, 3, 0, 0, tzinfo=UTC)
        d1_count = [r for r in count_rows if r.time == d1]
        assert len(d1_count) == 1
        assert float(d1_count[0].value) == 2.0  # two news items

    def test_idempotent_rerun(self, db_session: Session) -> None:
        asset = _make_asset(db_session, "FRA69TEST-S3")
        news = _make_news(db_session, asset, "surge", datetime(2024, 6, 3, 0, 0, tzinfo=UTC))
        _make_score(db_session, news, asset, news.published_at, score_val=0.6)

        compute_and_store_sentiment_factor(
            db_session,
            universe=[asset.id],
            start=date(2024, 6, 3),
            end=date(2024, 6, 7),
            model_name="fixture-model",
        )
        # Second run should not duplicate rows.
        compute_and_store_sentiment_factor(
            db_session,
            universe=[asset.id],
            start=date(2024, 6, 3),
            end=date(2024, 6, 7),
            model_name="fixture-model",
        )

        fv_rows = db_session.scalars(
            select(FactorValue).where(
                FactorValue.asset_id == asset.id,
                FactorValue.factor_name == SENTIMENT_FACTOR_NAME,
                FactorValue.source == "fixture-model",
            )
        ).all()
        d1 = datetime(2024, 6, 3, 0, 0, tzinfo=UTC)
        d1_rows = [r for r in fv_rows if r.time == d1]
        assert len(d1_rows) == 1  # not duplicated

    def test_no_data_returns_success_no_data(self, db_session: Session) -> None:
        asset = _make_asset(db_session, "FRA69TEST-S4")
        # No news, no scores.
        result = compute_and_store_sentiment_factor(
            db_session,
            universe=[asset.id],
            start=date(2024, 6, 3),
            end=date(2024, 6, 7),
            model_name="fixture-model",
        )
        assert result["status"] == "success_no_data"


# ---------------------------------------------------------------------------
# get_sentiment_summaries — DB
# ---------------------------------------------------------------------------


class TestGetSentimentSummaries:
    def test_returns_summaries(self, db_session: Session) -> None:
        asset = _make_asset(db_session, "FRA69TEST-M1")
        n1 = _make_news(db_session, asset, "surge", datetime(2024, 6, 3, 0, 0, tzinfo=UTC))
        n2 = _make_news(db_session, asset, "drop", datetime(2024, 6, 3, 0, 0, tzinfo=UTC))
        _make_score(db_session, n1, asset, n1.published_at, label="positive", score_val=0.6)
        _make_score(db_session, n2, asset, n2.published_at, label="negative", score_val=-0.4)

        summaries = get_sentiment_summaries(
            db_session,
            asset_ids=[asset.id],
            start=date(2024, 6, 3),
            end=date(2024, 6, 7),
            model_name="fixture-model",
        )
        assert len(summaries) == 1
        s = summaries[0]
        assert s.asset_id == str(asset.id)
        assert s.news_count == 2
        assert s.label_counts["positive"] == 1
        assert s.label_counts["negative"] == 1
        assert s.score == pytest.approx((0.6 + (-0.4)) / 2)

    def test_empty_returns_empty_list(self, db_session: Session) -> None:
        asset = _make_asset(db_session, "FRA69TEST-M2")
        summaries = get_sentiment_summaries(
            db_session,
            asset_ids=[asset.id],
            start=date(2024, 6, 3),
            end=date(2024, 6, 7),
            model_name="fixture-model",
        )
        assert summaries == []


# ---------------------------------------------------------------------------
# worker.tasks.sentiment.compute_sentiment_factor — RQ entry point
# ---------------------------------------------------------------------------


class TestWorkerComputeSentimentFactor:
    def test_task_persists_factor(self, db_session: Session) -> None:
        from worker.tasks.sentiment import compute_sentiment_factor as compute_task

        asset = _make_asset(db_session, "FRA69TEST-W1")
        news = _make_news(db_session, asset, "surge", datetime(2024, 6, 3, 0, 0, tzinfo=UTC))
        _make_score(db_session, news, asset, news.published_at, score_val=0.6)

        result = compute_task(
            asset_ids=[str(asset.id)],
            start="2024-06-03",
            end="2024-06-07",
            model_name="fixture-model",
        )
        assert result["status"] == "success"
        assert result["rows_written"] > 0
