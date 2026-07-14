"""News ingestion service — preflight + fetch + idempotent upsert (FRA-67).

Orchestrates the news pipeline: resolve the asset universe to symbols, dispatch
to a :class:`~app.services.sentiment.protocols.NewsProvider`, normalize contract
``NewsItem``s into ``news_items`` ORM rows, and upsert idempotently. Core logic
lives here (not in the RQ task) so the API and tests can call it directly
without importing the worker package — mirroring the factor-jobs pattern
(``app.services.factors.jobs``).

Anti-cheat / reproducibility (FRA-65 / FRA-66): the provider returns items with
``published_at`` as the earliest usable signal time; the upsert preserves the
exact source timestamp (no midnight normalization) and the raw payload for
audit. The idempotent conflict key is the 4-tuple
``(asset_id, source, published_at, headline_hash)`` so re-ingesting the same
article never duplicates a row.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.news import NewsItem as NewsItemModel
from app.services.sentiment.providers import get_news_provider
from app.services.sentiment.types import NewsItem as NewsItemContract

logger = logging.getLogger(__name__)

# Dedup conflict key — mirrors the unique constraint
# ``uq_news_items_asset_source_time_hash`` in models/news.py.
_NEWS_CONFLICT_COLUMNS = ["asset_id", "source", "published_at", "headline_hash"]


def _ensure_aware(dt: datetime) -> datetime:
    """Assume UTC for a naive datetime (news timestamps carry no reliable tz)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _headline_hash(headline: str) -> str:
    """sha256 hex of the headline — the content-based dedup key (FRA-66)."""
    return hashlib.sha256(headline.encode("utf-8")).hexdigest()


def upsert_news_items(db: Session, rows: list[dict[str, Any]]) -> tuple[int, int]:
    """幂等写入 news_items,返回 ``(inserted, updated)``。

    Uses ``ON CONFLICT (asset_id, source, published_at, headline_hash) DO
    UPDATE``. The ``xmax = 0`` trick distinguishes rows inserted this call from
    rows that already existed and were updated. Re-ingesting the same article is
    a no-op (updated count rises, no new row). This function does **not** commit
    — the caller controls the transaction, matching ``upsert_ohlcv_bars``.
    """
    if not rows:
        return (0, 0)
    # Two variables (base/stmt) avoid mypy's ReturningInsert -> Insert
    # assignment conflict — same idea as persist_factor_values. The trailing
    # .returning() widens the type past what mypy can infer for the local, so
    # pin it with a precise var-annotated ignore (ohlcv.py has the same shape).
    base = pg_insert(NewsItemModel).values(rows)
    stmt = base.on_conflict_do_update(  # type: ignore[var-annotated]
        index_elements=_NEWS_CONFLICT_COLUMNS,
        set_={
            "headline": base.excluded.headline,
            "summary": base.excluded.summary,
            "url": base.excluded.url,
            "provider_id": base.excluded.provider_id,
            "raw_payload": base.excluded.raw_payload,
        },
    ).returning(literal_column("(xmax = 0)").label("inserted"))
    result = db.execute(stmt)
    flags = [row.inserted for row in result]
    inserted = sum(1 for f in flags if f)
    updated = len(flags) - inserted
    return (inserted, updated)


def sync_news(
    asset_ids: list[uuid.UUID],
    start: datetime,
    end: datetime,
    provider_key: str | None = None,
) -> dict[str, Any]:
    """抓取新闻并幂等写入 ``news_items``。

    Pipeline:

    1. **preflight** — reject an invalid window (``start >= end`` or wider than
       ``NEWS_SYNC_MAX_WINDOW_DAYS``), then resolve + validate the provider
       (unknown key raises :class:`ValueError`).
    2. **asset resolve** — confirm every ``asset_id`` exists in ``assets`` and
       build the ``UUID → symbol`` / ``symbol → UUID`` maps (missing assets raise
       :class:`ValueError` with the full missing list).
    3. **fetch** — dispatch to the provider with provider-native symbols; the
       provider applies ``[start, end)`` and never touches the DB.
    4. **normalize** — map each contract ``NewsItem`` (``asset_id`` = symbol) to
       an ORM row: compute ``headline_hash``, assemble ``raw_payload``, resolve
       the symbol back to the DB ``UUID``.
    5. **upsert** — idempotent write via :func:`upsert_news_items`; commit on
       success, rollback + re-raise on failure (so RQ records ``exc_info``).

    Returns a result dict (``status`` = ``success`` | ``success_no_data``) for
    ``job.result`` / API responses. ``success_no_data`` means the provider
    returned no in-window items (uncovered universe or rate-limited feed) — not
    an error.
    """
    start = _ensure_aware(start)
    end = _ensure_aware(end)

    # --- preflight: window -------------------------------------------------
    if start >= end:
        raise ValueError(
            f"invalid window: start {start.isoformat()} must be before end {end.isoformat()}"
        )
    window_days = (end - start).days
    if window_days > settings.news_sync_max_window_days:
        raise ValueError(
            f"window too large: {window_days} days exceeds "
            f"NEWS_SYNC_MAX_WINDOW_DAYS={settings.news_sync_max_window_days}"
        )

    # --- preflight: provider (raises ValueError on unknown key) ------------
    resolved_provider = provider_key if provider_key is not None else settings.news_provider
    provider = get_news_provider(resolved_provider)

    db = SessionLocal()
    try:
        # --- preflight: assets exist + symbol mapping ----------------------
        result = db.execute(select(Asset.id, Asset.symbol).where(Asset.id.in_(asset_ids))).all()
        uuid_to_symbol: dict[uuid.UUID, str] = {row.id: row.symbol for row in result}
        found_ids = set(uuid_to_symbol)
        missing = [aid for aid in asset_ids if aid not in found_ids]
        if missing:
            raise ValueError(f"assets not found: {[str(m) for m in missing]}")
        symbol_to_uuid: dict[str, uuid.UUID] = {s: a for a, s in uuid_to_symbol.items()}

        # --- fetch (provider-native symbols) -------------------------------
        symbols = [uuid_to_symbol[aid] for aid in asset_ids]
        fetched: list[NewsItemContract] = list(provider.fetch(symbols, start, end))

        # --- normalize contract -> ORM rows --------------------------------
        now_iso = datetime.now(UTC).isoformat()
        orm_rows: list[dict[str, Any]] = []
        skipped: list[str] = []
        for item in fetched:
            asset_uuid = symbol_to_uuid.get(item.asset_id)
            if asset_uuid is None:
                # Provider returned a symbol we didn't ask for / can't resolve.
                skipped.append(item.asset_id)
                continue
            raw_meta = item.params.get("raw") if item.params else None
            raw_payload: dict[str, Any] = {
                "provider": resolved_provider,
                "fetched_at": now_iso,
            }
            if isinstance(raw_meta, dict):
                raw_payload["raw"] = raw_meta
            orm_rows.append(
                {
                    "asset_id": asset_uuid,
                    "source": item.source,
                    "published_at": item.published_at,
                    "headline": item.headline,
                    "headline_hash": _headline_hash(item.headline),
                    "summary": item.summary,
                    "url": item.url,
                    "provider_id": None,
                    "raw_payload": raw_payload,
                }
            )
        if skipped:
            logger.warning("news items for unresolved symbols skipped: %s", skipped)

        # --- upsert (idempotent) -------------------------------------------
        inserted, updated = upsert_news_items(db, orm_rows)
        db.commit()

        total = len(orm_rows)
        status_value = "success" if total > 0 else "success_no_data"
        warning = (
            None
            if total > 0
            else "provider returned 0 news items (uncovered universe or rate-limited feed)"
        )
        logger.info(
            "sync_news provider=%s assets=%d [%s..%s] fetched=%d inserted=%d updated=%d status=%s",
            resolved_provider,
            len(asset_ids),
            start.isoformat(),
            end.isoformat(),
            total,
            inserted,
            updated,
            status_value,
        )
        return {
            "provider": resolved_provider,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "assets": len(asset_ids),
            "fetched": total,
            "inserted": inserted,
            "updated": updated,
            "status": status_value,
            "warning": warning,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
