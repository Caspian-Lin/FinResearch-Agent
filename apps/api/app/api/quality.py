"""On-demand OHLCV data-quality router (FRA-9).

Exposes ``GET /quality/{asset_id}`` — computes a quality report for one
``(asset, source)`` pair over a ``[start, end]`` window. The report is
calculated per request; Week 1 does **not** persist ``data_quality_reports``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.asset import Asset
from app.models.ohlcv import Ohlcv
from app.schemas.quality import QualityReport
from app.services.quality import compute_quality

router = APIRouter(prefix="/quality", tags=["quality"])

# Dependency aliases — keeping defaults free of Query(...) calls satisfies
# ruff B008 and keeps the handler signature readable.
DBSession = Annotated[Session, Depends(get_db)]


@router.get(
    "/{asset_id}",
    response_model=QualityReport,
    summary="Compute OHLCV data-quality report",
)
def get_quality(
    asset_id: uuid.UUID,
    db: DBSession,
    source: Annotated[str, Query(description="Data source to evaluate")],
    start: Annotated[date, Query(description="Window start (inclusive)")],
    end: Annotated[date, Query(description="Window end (inclusive)")],
) -> QualityReport:
    """Compute a quality report for one asset/source over ``[start, end]``.

    Expected trading sessions come from the asset's exchange calendar
    (holidays/weekends excluded); observed sessions are the trading days that
    actually have bars. Anomalies (bad prices/volume, large returns) are
    flagged per bar. An unknown asset yields ``404``; ``start > end`` or an
    exchange with no known calendar yields ``422``.
    """
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset {asset_id} not found.",
        )

    if start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start must be <= end",
        )

    # end-day inclusive => [start, start_of_next_day_after_end)
    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    bars = list(
        db.scalars(
            select(Ohlcv)
            .where(
                Ohlcv.asset_id == asset_id,
                Ohlcv.source == source,
                Ohlcv.time >= start_dt,
                Ohlcv.time < end_dt,
            )
            .order_by(Ohlcv.time)
        )
    )

    try:
        return compute_quality(
            asset, source, start, end, bars, settings.quality_large_return_threshold
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
