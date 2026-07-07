"""Sentiment classification orchestrator (FRA-68).

Reads ``news_items`` from the DB, dispatches them to a
:class:`~app.services.sentiment.classifier.SentimentClassifier` in batches, and
upserts the resulting ``SentimentScore``s idempotently into ``sentiment_scores``.
Core logic lives here (not in the RQ task) so the API and tests can call it
directly — mirroring :mod:`app.services.sentiment.ingest`.

Anti-cheat / reproducibility (FRA-65 / FRA-66): ``published_at`` is preserved
verbatim from the source news item (no midnight normalization); the idempotent
conflict key is ``(news_item_id, model_name)`` so re-classifying under the same
model overwrites in place without duplicating rows. Classifier output floats
are clamped to their valid ranges and coerced to ``Numeric(10,6)`` on write.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.news import NewsItem as NewsItemModel
from app.models.news import SentimentScore as SentimentScoreModel
from app.services.sentiment.classifier import get_sentiment_classifier
from app.services.sentiment.types import NewsItem, SentimentScore

logger = logging.getLogger(__name__)

# Dedup conflict key — mirrors the unique constraint
# ``uq_sentiment_scores_news_model`` in models/news.py.
_SCORE_CONFLICT_COLUMNS = ["news_item_id", "model_name"]


def upsert_sentiment_scores(db: Session, rows: list[dict[str, Any]]) -> tuple[int, int]:
    """幂等写入 sentiment_scores,返回 ``(inserted, updated)``。

    Uses ``ON CONFLICT (news_item_id, model_name) DO UPDATE``. The ``xmax = 0``
    trick distinguishes rows inserted this call from rows updated. Re-classifying
    the same news item under the same model overwrites in place. This function
    does **not** commit — the caller controls the transaction.
    """
    if not rows:
        return (0, 0)
    # base/stmt two variables avoid mypy's ReturningInsert -> Insert assignment
    # conflict (same pattern as upsert_news_items).
    base = pg_insert(SentimentScoreModel).values(rows)
    stmt = base.on_conflict_do_update(  # type: ignore[var-annotated]
        index_elements=_SCORE_CONFLICT_COLUMNS,
        set_={
            "asset_id": base.excluded.asset_id,
            "published_at": base.excluded.published_at,
            "label": base.excluded.label,
            "score": base.excluded.score,
            "confidence": base.excluded.confidence,
            "raw_response": base.excluded.raw_response,
            "params": base.excluded.params,
        },
    ).returning(literal_column("(xmax = 0)").label("inserted"))
    result = db.execute(stmt)
    flags = [row.inserted for row in result]
    inserted = sum(1 for f in flags if f)
    updated = len(flags) - inserted
    return (inserted, updated)


def classify_news_items(
    news_item_ids: list[uuid.UUID],
    classifier_key: str | None = None,
) -> dict[str, Any]:
    """对给定 news_items 批量分类并幂等写入 ``sentiment_scores``。

    Pipeline:

    1. **preflight** — reject an oversized batch (>
       ``SENTIMENT_CLASSIFY_MAX_ITEMS``), then resolve + validate the classifier
       (unknown key raises :class:`ValueError`).
    2. **load** — fetch the ``news_items`` rows; missing ids raise
       :class:`ValueError` with the full missing list.
    3. **classify** — convert ORM rows to contract ``NewsItem``s and dispatch in
       batches of ``SENTIMENT_CLASSIFY_BATCH_SIZE``. Items the classifier skips
       (e.g. LLM parse failure) produce no score and are counted as skipped.
    4. **normalize** — match each returned ``SentimentScore`` back to its
       ``news_item_id`` via ``(asset_id, source, published_at, headline)``,
       coerce floats to ``Decimal`` (clamped to valid ranges upstream).
    5. **upsert** — idempotent write via :func:`upsert_sentiment_scores`;
       commit on success, rollback + re-raise on failure.

    Returns a result dict (``status`` = ``success`` | ``success_no_data``).
    ``success_no_data`` means nothing was classified (empty input or all
    skipped) — not an error.
    """
    if not news_item_ids:
        return {
            "classifier": None,
            "news": 0,
            "classified": 0,
            "skipped": 0,
            "inserted": 0,
            "updated": 0,
            "status": "success_no_data",
        }

    if len(news_item_ids) > settings.sentiment_classify_max_items:
        raise ValueError(
            f"too many news items: {len(news_item_ids)} exceeds "
            f"SENTIMENT_CLASSIFY_MAX_ITEMS={settings.sentiment_classify_max_items}"
        )

    resolved_classifier = (
        classifier_key if classifier_key is not None else settings.sentiment_classifier
    )
    classifier = get_sentiment_classifier(resolved_classifier)

    db = SessionLocal()
    try:
        # --- load news_items ------------------------------------------------
        news_rows = (
            db.execute(select(NewsItemModel).where(NewsItemModel.id.in_(news_item_ids)))
            .scalars()
            .all()
        )
        found_ids = {n.id for n in news_rows}
        missing = [nid for nid in news_item_ids if nid not in found_ids]
        if missing:
            raise ValueError(f"news_items not found: {[str(m) for m in missing]}")

        # Index by (asset_id, source, published_at, headline) -> news_item_id
        # so we can re-attach scores after the classifier (which may skip items,
        # breaking positional correspondence). This tuple is unique under the
        # news_items unique constraint (headline_hash = sha256(headline)).
        news_index: dict[tuple[str, str, datetime, str], uuid.UUID] = {}
        for n in news_rows:
            news_index[(str(n.asset_id), n.source, n.published_at, n.headline)] = n.id

        # --- classify in batches -------------------------------------------
        batch_size = settings.sentiment_classify_batch_size
        all_scores: list[SentimentScore] = []
        for i in range(0, len(news_rows), batch_size):
            batch = news_rows[i : i + batch_size]
            contract_items = [
                NewsItem(
                    asset_id=str(n.asset_id),
                    published_at=n.published_at,
                    source=n.source,
                    headline=n.headline,
                    summary=n.summary,
                    url=n.url,
                )
                for n in batch
            ]
            all_scores.extend(classifier.classify(contract_items))

        # --- normalize + re-attach to news_item_id -------------------------
        orm_rows: list[dict[str, Any]] = []
        unmatched = 0
        for score in all_scores:
            key = (score.asset_id, score.source, score.published_at, score.headline)
            news_id = news_index.get(key)
            if news_id is None:
                unmatched += 1
                logger.warning(
                    "sentiment score could not be matched back to a news_item: %s",
                    key,
                )
                continue
            params = dict(score.params) if score.params else {}
            # ORM has no prompt_version column (FRA-66): it is captured in the
            # params JSONB alongside the other reproducibility metadata.
            params["prompt_version"] = score.prompt_version
            orm_rows.append(
                {
                    "news_item_id": news_id,
                    "asset_id": uuid.UUID(score.asset_id),
                    "published_at": score.published_at,
                    "model_name": score.model_name,
                    "label": score.label,
                    "score": Decimal(str(score.score)),
                    "confidence": (
                        Decimal(str(score.confidence)) if score.confidence is not None else None
                    ),
                    "raw_response": dict(score.raw_response) if score.raw_response else None,
                    "params": params,
                }
            )

        total = len(orm_rows)
        skipped = len(news_rows) - total

        # --- upsert (idempotent) -------------------------------------------
        inserted, updated = upsert_sentiment_scores(db, orm_rows)
        db.commit()

        status_value = "success" if total > 0 else "success_no_data"
        logger.info(
            "classify_news_items classifier=%s news=%d classified=%d skipped=%d "
            "inserted=%d updated=%d status=%s",
            resolved_classifier,
            len(news_rows),
            total,
            skipped,
            inserted,
            updated,
            status_value,
        )
        return {
            "classifier": resolved_classifier,
            "news": len(news_rows),
            "classified": total,
            "skipped": skipped,
            "inserted": inserted,
            "updated": updated,
            "status": status_value,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
