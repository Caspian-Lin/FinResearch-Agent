"""Sentiment pipeline behaviour protocols (FRA-65).

Protocols define provider, classifier, and factor-construction boundaries for
later Week-4 implementation issues while keeping this spike implementation-free.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

import pandas as pd

from app.services.sentiment.types import NewsItem, SentimentScore


@runtime_checkable
class NewsProvider(Protocol):
    """Fetch raw financial news for an asset universe and publication window.

    Implementations return only items with ``published_at`` inside
    ``[start, end)``. They should preserve missing coverage by returning an
    empty sequence for uncovered assets/windows instead of synthesizing rows.
    """

    def fetch(
        self,
        asset_ids: Sequence[str],
        start: datetime,
        end: datetime,
    ) -> Sequence[NewsItem]:
        """Return raw news items in publication-time order when available."""
        ...


@runtime_checkable
class SentimentClassifier(Protocol):
    """Classify news text into reproducible normalized sentiment scores.

    Outputs must include ``model_name``, ``prompt_version``, and parameter
    snapshots so later storage/API layers can reproduce the scoring setup.
    """

    def classify(self, items: Sequence[NewsItem]) -> Sequence[SentimentScore]:
        """Return one score per classified news item."""
        ...


@runtime_checkable
class SentimentFactor(Protocol):
    """Convert item-level sentiment scores into a decision-date factor frame.

    The returned frame follows the Week-3 factor convention: index = UTC
    midnight decision dates, columns = ``asset_id``. A score published after a
    decision point must map to a later row, never to the earlier trading day.
    Missing source coverage stays ``NaN``; implementations must not forward-fill
    sentiment across trading dates.
    """

    def compute(
        self,
        scores: Sequence[SentimentScore],
        trading_calendar: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Return a sentiment factor wide-frame aligned to ``trading_calendar``."""
        ...
