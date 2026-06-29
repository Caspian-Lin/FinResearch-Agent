"""Sentiment research contracts and behaviour protocols (FRA-65)."""

from app.services.sentiment.protocols import (
    NewsProvider,
    SentimentClassifier,
    SentimentFactor,
)
from app.services.sentiment.types import (
    NewsItem,
    SentimentLabel,
    SentimentScore,
    SentimentSummary,
)

__all__ = [
    "NewsItem",
    "NewsProvider",
    "SentimentClassifier",
    "SentimentFactor",
    "SentimentLabel",
    "SentimentScore",
    "SentimentSummary",
]
