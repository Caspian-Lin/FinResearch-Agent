"""Sentiment factor service — DB read → daily aggregate → optional persist (FRA-69).

Connects ``sentiment_scores`` to the Week-3 factor / backtest research layer.
Reads item-level scores from the DB, builds a trading calendar (same
exchange-calendar logic as ``load_prices``), computes the daily mean-score
factor frame via :class:`DailySentimentFactor`, and optionally persists it to
``factor_values`` so existing IC / quantile / sweep pipelines can consume the
sentiment factor transparently.

Anti-cheat (FRA-65): ``published_at`` is preserved verbatim from the source;
the daily aggregation maps each score to a decision date **at or after** its
publication. Missing coverage (a trading day with no mapped news) stays
``NaN`` — no forward-fill of stale sentiment.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.news import NewsItem as NewsItemModel
from app.models.news import SentimentScore as SentimentScoreModel
from app.services.factors.service import persist_factor_values
from app.services.quality import expected_sessions
from app.services.sentiment.factor import (
    DailySentimentFactor,
    _to_utc_timestamp,
    build_sentiment_summaries,
)
from app.services.sentiment.types import SentimentScore, SentimentSummary

logger = logging.getLogger(__name__)

#: Factor name under which the daily mean-score sentiment factor is stored in
#: ``factor_values``. ``source`` encodes the classifier model name so different
#: models don't collide (PK = asset_id, factor_name, time, source).
SENTIMENT_FACTOR_NAME = "sentiment_score"
SENTIMENT_NEWS_COUNT_FACTOR_NAME = "sentiment_news_count"

#: Lookback (calendar days) when reading raw scores from the DB. Scores
#: published before ``start - _SCORE_READ_LOOKBACK_DAYS`` are excluded; the
#: generous 7-day margin covers weekends + common holidays so overnight /
#: pre-market news still maps to the first trading day.
_SCORE_READ_LOOKBACK_DAYS = 7

_daily_factor = DailySentimentFactor()


def read_sentiment_scores(
    db: Session,
    *,
    asset_ids: Sequence[uuid.UUID],
    start: date,
    end: date,
    model_name: str,
) -> list[SentimentScore]:
    """Read ``sentiment_scores`` joined with ``news_items`` → contract list.

    The join supplies ``source`` / ``headline`` / ``summary`` / ``url`` (which
    live on ``news_items``, not ``sentiment_scores``). ``prompt_version`` is
    recovered from the ``params`` JSONB column.

    A generous lookback (``start - 7 days``) ensures overnight or weekend news
    is included so the first trading day's aggregate is complete. Scores whose
    ``published_at`` maps past ``end`` are naturally dropped by the downstream
    factor computation.
    """
    read_start = datetime.combine(
        start - timedelta(days=_SCORE_READ_LOOKBACK_DAYS),
        datetime.min.time(),
        tzinfo=UTC,
    )
    read_end = datetime.combine(
        end + timedelta(days=1),
        datetime.min.time(),
        tzinfo=UTC,
    )

    rows = db.execute(
        select(
            SentimentScoreModel.asset_id,
            SentimentScoreModel.published_at,
            SentimentScoreModel.model_name,
            SentimentScoreModel.label,
            SentimentScoreModel.score,
            SentimentScoreModel.confidence,
            SentimentScoreModel.raw_response,
            SentimentScoreModel.params,
            NewsItemModel.source.label("news_source"),
            NewsItemModel.headline,
            NewsItemModel.summary,
            NewsItemModel.url,
        )
        .join(NewsItemModel, SentimentScoreModel.news_item_id == NewsItemModel.id)
        .where(
            SentimentScoreModel.asset_id.in_(list(asset_ids)),
            SentimentScoreModel.model_name == model_name,
            SentimentScoreModel.published_at >= read_start,
            SentimentScoreModel.published_at < read_end,
        )
        .order_by(SentimentScoreModel.published_at)
    ).all()

    out: list[SentimentScore] = []
    for r in rows:
        params = dict(r.params) if r.params else {}
        prompt_version = str(params.get("prompt_version", "unknown"))
        out.append(
            SentimentScore(
                asset_id=str(r.asset_id),
                published_at=r.published_at,
                source=r.news_source,
                headline=r.headline,
                model_name=r.model_name,
                prompt_version=prompt_version,
                label=r.label,
                score=float(r.score),
                confidence=float(r.confidence) if r.confidence is not None else 0.0,
                summary=r.summary,
                url=r.url,
                raw_response=dict(r.raw_response) if r.raw_response else None,
                params=params,
            )
        )
    return out


def _build_trading_calendar(
    db: Session,
    asset_ids: Sequence[uuid.UUID],
    start: date,
    end: date,
) -> pd.DatetimeIndex:
    """Union of trading days across the universe's exchanges (UTC midnight).

    Mirrors ``_trading_index`` in ``backtest/prices.py`` so the sentiment factor
    shares the same calendar as price factors.
    """
    asset_rows = db.execute(select(Asset.exchange).where(Asset.id.in_(list(asset_ids)))).all()
    exchanges = {row.exchange for row in asset_rows}
    if not exchanges:
        raise ValueError("universe has no assets with known exchanges")

    days: set[date] = set()
    for exchange in exchanges:
        days.update(expected_sessions(exchange, start, end))
    if not days:
        raise ValueError(f"no trading sessions for exchanges={exchanges} in [{start}, {end}]")
    return pd.DatetimeIndex(pd.Timestamp(d, tz="UTC") for d in sorted(days))


def compute_sentiment_factor(
    db: Session,
    *,
    asset_ids: Sequence[uuid.UUID],
    start: date,
    end: date,
    model_name: str,
) -> pd.DataFrame:
    """Compute the daily mean-score sentiment factor wide-frame.

    Pipeline: build trading calendar → read scores → :meth:`DailySentimentFactor.compute`.

    Returns a wide ``DataFrame``: index = UTC-midnight trading days,
    columns = ``str(asset_id)``, values = mean sentiment score (``NaN`` for
    days with no news).
    """
    if not asset_ids:
        raise ValueError("asset_ids must contain at least one UUID")
    if start > end:
        raise ValueError(f"start ({start}) must be <= end ({end})")

    calendar = _build_trading_calendar(db, asset_ids, start, end)
    scores = read_sentiment_scores(
        db, asset_ids=asset_ids, start=start, end=end, model_name=model_name
    )
    return _daily_factor.compute(scores, calendar)


def compute_and_store_sentiment_factor(
    db: Session,
    *,
    universe: Sequence[uuid.UUID],
    start: date,
    end: date,
    model_name: str,
) -> dict[str, Any]:
    """Compute the sentiment factor and persist it to ``factor_values``.

    Stores two factor series:
    * ``sentiment_score`` — daily mean score (``NaN`` cells skipped, NOT NULL).
    * ``sentiment_news_count`` — daily news count (integer-valued, skipped when 0).

    ``source`` = ``model_name`` so re-running under a different classifier
    doesn't overwrite (PK includes ``source``).

    Returns a summary dict for ``job.result`` / API responses.
    """
    if not universe:
        raise ValueError("universe must contain at least one asset_id")
    if start > end:
        raise ValueError(f"start ({start}) must be <= end ({end})")

    calendar = _build_trading_calendar(db, universe, start, end)
    scores = read_sentiment_scores(
        db, asset_ids=universe, start=start, end=end, model_name=model_name
    )

    score_frame = _daily_factor.compute(scores, calendar)

    # Build a news-count frame from the same mapping.
    if scores:
        pub_values = pd.DatetimeIndex([_to_utc_timestamp(s.published_at) for s in scores])
        positions = calendar.searchsorted(pub_values, side="left")
        valid = positions < len(calendar)
        count_records: list[dict[str, object]] = []
        for i, s in enumerate(scores):
            if not valid[i]:
                continue
            count_records.append({"signal_date": calendar[positions[i]], "asset_id": s.asset_id})
        if count_records:
            count_long = pd.DataFrame(count_records)
            count_daily = count_long.groupby(["signal_date", "asset_id"]).size().rename("count")
            count_frame = count_daily.unstack("asset_id")
            count_frame.columns = [str(c) for c in count_frame.columns]
            count_frame = count_frame.reindex(calendar).fillna(0).astype("float64")
        else:
            count_frame = pd.DataFrame(0.0, index=calendar, columns=[], dtype="float64")
    else:
        count_frame = pd.DataFrame(0.0, index=calendar, columns=[], dtype="float64")

    asset_id_by_col = {col: uuid.UUID(col) for col in score_frame.columns}

    rows_written = persist_factor_values(
        db,
        factor_frames={SENTIMENT_FACTOR_NAME: score_frame},
        asset_id_by_col=asset_id_by_col,
        source=model_name,
    )
    rows_written += persist_factor_values(
        db,
        factor_frames={SENTIMENT_NEWS_COUNT_FACTOR_NAME: count_frame},
        asset_id_by_col={col: uuid.UUID(col) for col in count_frame.columns},
        source=model_name,
    )

    status = "success" if rows_written > 0 else "success_no_data"
    logger.info(
        "compute_and_store_sentiment_factor model=%s assets=%d [%s..%s] scores=%d "
        "rows_written=%d status=%s",
        model_name,
        len(universe),
        start.isoformat(),
        end.isoformat(),
        len(scores),
        rows_written,
        status,
    )
    return {
        "model_name": model_name,
        "assets": len(universe),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "scores_read": len(scores),
        "rows_written": rows_written,
        "status": status,
    }


def get_sentiment_summaries(
    db: Session,
    *,
    asset_ids: Sequence[uuid.UUID],
    start: date,
    end: date,
    model_name: str,
    window_days: int = 7,
) -> list[SentimentSummary]:
    """Build per ``(signal_date, asset_id)`` :class:`SentimentSummary` list.

    Used by the sentiment API to return rich aggregates (news_count,
    label_counts, confidence) alongside the factor value.
    """
    calendar = _build_trading_calendar(db, asset_ids, start, end)
    scores = read_sentiment_scores(
        db, asset_ids=asset_ids, start=start, end=end, model_name=model_name
    )
    if not scores:
        return []

    prompt_version = str(scores[0].prompt_version) if scores else "unknown"
    return build_sentiment_summaries(
        scores,
        calendar,
        model_name=model_name,
        prompt_version=prompt_version,
        window_days=window_days,
    )
