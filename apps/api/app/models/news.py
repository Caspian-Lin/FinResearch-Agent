"""News + sentiment ORM models — Week 4 text/sentiment storage (FRA-66).

Persists news headlines/summaries and classifier sentiment scores so the text
factor pipeline is reproducible and auditable, joined to ``assets`` (and thus to
``factor_values`` / ``backtest_runs``) via ``asset_id``. Field semantics mirror
the FRA-65 in-memory contracts in ``app.services.sentiment.types``: classifier
reproducibility metadata (``model_name`` + ``prompt_version`` + params snapshot)
lands in ``sentiment_scores.params`` (JSONB), and the raw provider/model payload
is preserved verbatim in ``raw_response`` / ``raw_payload`` for audit.

Not TimescaleDB hypertables: news and sentiment are sparse event tables, not the
append-continuous series ``ohlcv`` / ``factor_values`` are. ``published_at`` is
the earliest point a text signal may influence a factor (anti-cheat, FRA-65) and
is used for query/sort order, not partitioning.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NewsItem(Base):
    """One source news headline/summary for one asset.

    ``headline_hash`` (sha256 hex of ``headline``) backs the content-based dedup
    unique constraint so re-ingesting the same article is idempotent even when a
    source exposes no stable ``provider_id``. ``provider_id`` remains nullable and
    is stored when available for source-native dedup/traceability.
    """

    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "source",
            "published_at",
            "headline_hash",
            name="uq_news_items_asset_source_time_hash",
        ),
        Index("ix_news_items_asset_id_published_at", "asset_id", "published_at"),
        Index("ix_news_items_source_published_at", "source", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    headline_hash: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SentimentScore(Base):
    """Classifier output for one ``NewsItem`` (1:N — multiple models per item).

    ``score`` is normalized to ``[-1, 1]`` (bearish..bullish), ``confidence`` to
    ``[0, 1]``, and ``label`` is one of ``{positive, neutral, negative}`` (the
    FRA-65 ``SentimentLabel`` literal). ``label`` is free TEXT at the DB layer —
    the value domain is enforced at the service layer so label-taxonomy changes
    don't require a migration. ``model_name`` + ``prompt_version`` + classifier
    params are captured in ``params`` (JSONB); the provider/model payload is in
    ``raw_response``.
    """

    __tablename__ = "sentiment_scores"
    __table_args__ = (
        UniqueConstraint("news_item_id", "model_name", name="uq_sentiment_scores_news_model"),
        Index("ix_sentiment_scores_model_name_published_at", "model_name", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    news_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_items.id"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
