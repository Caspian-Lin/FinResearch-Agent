"""sync_ohlcv RQ task (FRA-8).

Enqueued by ``POST /sync``. Resolves the asset's ``(symbol, exchange)``,
fetches bars from the source, and idempotently upserts. Returns a result dict
stored on ``job.result`` for ``GET /sync/{job_id}``. On failure, rolls back and
re-raises so RQ marks the job failed and records ``exc_info``.

Args are passed as strings (RQ-serialization friendly); parsed inside.

Note: ``app`` is the apps/api package name (a uv workspace member). The worker
imports it at runtime, which holds in local dev where the repo root is on the
path. For Docker deployments apps/api must be mounted into the worker image —
see the PR description.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from app.db.session import SessionLocal
from app.models.asset import Asset
from app.services.ohlcv import upsert_ohlcv_bars
from app.services.yfinance import fetch_ohlcv

logger = logging.getLogger(__name__)

SUPPORTED_SOURCES = ("yfinance",)


def sync_ohlcv(asset_id: str, start: str, end: str, source: str = "yfinance") -> dict[str, Any]:
    """Sync OHLCV for ``asset_id`` over ``[start, end]`` from ``source``.

    Args:
        asset_id: UUID of the asset (string — RQ serializes args via Redis).
        start: ISO date string, inclusive.
        end: ISO date string, inclusive.
        source: Data source key; must be in ``SUPPORTED_SOURCES``.

    Returns:
        A result dict written onto ``job.result`` and surfaced by
        ``GET /sync/{job_id}``. Includes ``inserted``/``updated`` counts from
        the upsert and ``total_bars`` fetched.

    Raises:
        ValueError: If ``source`` is unsupported or the asset does not exist.
            Re-raised after rollback so RQ records ``exc_info``.
    """
    aid = uuid.UUID(str(asset_id))
    start_d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"unsupported source: {source}")

    db = SessionLocal()
    try:
        asset = db.get(Asset, aid)
        if asset is None:
            raise ValueError(f"asset {aid} not found")
        bars = fetch_ohlcv(asset.symbol, start_d, end_d)  # retry lives inside fetch
        inserted, updated = upsert_ohlcv_bars(db, aid, source, bars)
        db.commit()
        logger.info(
            "sync_ohlcv asset_id=%s source=%s [%s..%s] inserted=%d updated=%d",
            aid,
            source,
            start,
            end,
            inserted,
            updated,
        )
        return {
            "asset_id": str(aid),
            "source": source,
            "start": start,
            "end": end,
            "inserted": inserted,
            "updated": updated,
            "total_bars": len(bars),
            "status": "success",
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
