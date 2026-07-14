from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from app.services.sentiment import (
    NewsItem,
    NewsProvider,
    SentimentClassifier,
    SentimentFactor,
    SentimentScore,
    SentimentSummary,
)


class StaticNewsProvider:
    def fetch(
        self,
        asset_ids: list[str],
        start: datetime,
        end: datetime,
    ) -> list[NewsItem]:
        return [
            NewsItem(
                asset_id=asset_ids[0],
                published_at=start,
                source="fixture",
                headline="Company raises guidance",
            )
        ]


class StaticSentimentClassifier:
    def classify(self, items: list[NewsItem]) -> list[SentimentScore]:
        item = items[0]
        return [
            SentimentScore(
                asset_id=item.asset_id,
                published_at=item.published_at,
                source=item.source,
                headline=item.headline,
                model_name="fixture-model",
                prompt_version="sentiment-v1",
                label="positive",
                score=0.7,
                confidence=0.9,
                params={"temperature": 0},
            )
        ]


class StaticSentimentFactor:
    def compute(
        self,
        scores: list[SentimentScore],
        trading_calendar: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        frame = pd.DataFrame(index=trading_calendar, columns=[scores[0].asset_id], dtype=float)
        frame.iloc[-1, 0] = scores[0].score
        return frame


def test_sentiment_protocols_are_runtime_checkable() -> None:
    assert isinstance(StaticNewsProvider(), NewsProvider)
    assert isinstance(StaticSentimentClassifier(), SentimentClassifier)
    assert isinstance(StaticSentimentFactor(), SentimentFactor)


def test_sentiment_contracts_keep_reproducibility_fields() -> None:
    published_at = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    score = SentimentScore(
        asset_id="AAPL",
        published_at=published_at,
        source="fixture",
        headline="Company raises guidance",
        model_name="gpt-fixture",
        prompt_version="sentiment-v1",
        label="positive",
        score=0.8,
        confidence=0.95,
        raw_response={"label": "positive"},
        params={"temperature": 0, "schema_version": 1},
    )
    summary = SentimentSummary(
        asset_id="AAPL",
        signal_date=pd.Timestamp("2026-01-06T00:00:00Z"),
        window_start=published_at,
        window_end=datetime(2026, 1, 6, tzinfo=UTC),
        model_name=score.model_name,
        prompt_version=score.prompt_version,
        score=score.score,
        confidence=score.confidence,
        news_count=1,
        label_counts={"positive": 1, "neutral": 0, "negative": 0},
        params={"alignment": "next_decision_time"},
    )

    assert score.model_name == "gpt-fixture"
    assert score.prompt_version == "sentiment-v1"
    assert score.params["temperature"] == 0
    assert summary.signal_date >= pd.Timestamp(score.published_at)
    assert summary.news_count == 1
