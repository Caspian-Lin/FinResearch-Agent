"""Financial-text sentiment data contracts (FRA-65).

These are typed stubs for the Week-4 sentiment pipeline. They define the
in-memory shapes shared by news ingestion, classifier services, factor
construction, storage schemas, and API responses; no provider calls or model
logic live here.

Anti-cheat boundary: a text signal becomes usable only after ``published_at``.
Downstream factor alignment must map each score to a decision date at or after
publication, never to an earlier trading day. Missing source coverage remains
missing and must not be forward-filled.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import pandas as pd

SentimentLabel = Literal["positive", "neutral", "negative"]


@dataclass(frozen=True, slots=True)
class NewsItem:
    """One source news headline/summary for one asset.

    ``published_at`` is the source publication timestamp and is the earliest
    point at which the text may influence a factor. ``asset_id`` uses the same
    identifier as OHLCV / factor contracts. ``summary`` and ``url`` are optional
    because sources often expose only headlines or omit stable URLs.
    """

    asset_id: str
    published_at: datetime
    source: str
    headline: str
    summary: str | None = None
    url: str | None = None
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SentimentScore:
    """Classifier output for one ``NewsItem``.

    ``score`` is normalized to ``[-1.0, 1.0]`` where negative values are bearish,
    zero is neutral, and positive values are bullish. ``confidence`` is
    normalized to ``[0.0, 1.0]``. ``model_name``, ``prompt_version``, and
    ``params`` are required reproducibility metadata; ``raw_response`` preserves
    the provider/model payload for audit without constraining the classifier
    implementation.
    """

    asset_id: str
    published_at: datetime
    source: str
    headline: str
    model_name: str
    prompt_version: str
    label: SentimentLabel
    score: float
    confidence: float
    summary: str | None = None
    url: str | None = None
    raw_response: Mapping[str, Any] | None = None
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SentimentSummary:
    """Daily decision-date sentiment aggregate for one asset.

    ``signal_date`` is the trading decision date, represented as UTC midnight
    and never earlier than any included score's ``published_at``. ``window_start``
    and ``window_end`` record the text window used for the aggregate.
    ``news_count == 0`` means missing coverage; consumers must keep it missing
    instead of forward-filling a prior sentiment value.
    """

    asset_id: str
    signal_date: pd.Timestamp
    window_start: datetime
    window_end: datetime
    model_name: str
    prompt_version: str
    score: float | None
    confidence: float | None
    news_count: int
    label_counts: Mapping[SentimentLabel, int] = field(default_factory=dict)
    source: str = "computed"
    params: Mapping[str, Any] = field(default_factory=dict)
