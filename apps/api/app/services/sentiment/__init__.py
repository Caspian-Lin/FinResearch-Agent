"""Sentiment research contracts, services, and behaviour protocols (FRA-65..71)."""

from app.services.sentiment.factor import DailySentimentFactor, build_sentiment_summaries
from app.services.sentiment.protocols import (
    NewsProvider,
    SentimentClassifier,
    SentimentFactor,
)
from app.services.sentiment.service import (
    SENTIMENT_FACTOR_NAME,
    SENTIMENT_NEWS_COUNT_FACTOR_NAME,
    compute_and_store_sentiment_factor,
    compute_sentiment_factor,
    get_sentiment_summaries,
    read_sentiment_scores,
)
from app.services.sentiment.types import (
    NewsItem,
    SentimentLabel,
    SentimentScore,
    SentimentSummary,
)

__all__ = [
    "DailySentimentFactor",
    "NewsItem",
    "NewsProvider",
    "SENTIMENT_FACTOR_NAME",
    "SENTIMENT_NEWS_COUNT_FACTOR_NAME",
    "SentimentClassifier",
    "SentimentFactor",
    "SentimentLabel",
    "SentimentScore",
    "SentimentSummary",
    "build_sentiment_summaries",
    "compute_and_store_sentiment_factor",
    "compute_sentiment_factor",
    "get_sentiment_summaries",
    "read_sentiment_scores",
]
