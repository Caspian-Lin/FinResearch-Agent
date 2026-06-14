"""OHLCV read-only router (FRA-15).

Exposes ``GET /ohlcv`` — a keyset-cursor-paginated listing of OHLCV bars
scoped to a single ``(asset_id, source)`` pair with an optional
``[start, end]`` time window. Writes happen via the FRA-8 sync task; this
router never mutates state.

Cursor pagination orders by ``(time, source)`` ascending and uses Postgres
row-value comparison so paging is stable and neither drops nor duplicates
rows, even if new bars are inserted concurrently.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.asset import Asset
from app.models.ohlcv import Ohlcv
from app.schemas.ohlcv import OhlcvPage

router = APIRouter(prefix="/ohlcv", tags=["ohlcv"])

# Dependency aliases — defaults stay plain values (not Query(...) calls) so
# ruff B008 is satisfied and the handler signature reads cleanly.
DBSession = Annotated[Session, Depends(get_db)]
LimitParam = Annotated[int, Query(ge=1, le=1000)]


def _encode_cursor(row: Ohlcv) -> str:
    """Encode the last row's sort key into an opaque pagination cursor."""
    payload = json.dumps({"time": row.time.isoformat(), "source": row.source})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode a cursor back into its ``(time, source)`` sort key.

    Raises 422 when the cursor is malformed so callers can restart paging.
    """
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(data["time"]), str(data["source"])
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid cursor",
        ) from exc


@router.get(
    "",
    response_model=OhlcvPage,
    summary="List OHLCV bars (cursor-paginated)",
)
def list_ohlcv(
    db: DBSession,
    asset_id: uuid.UUID,
    source: str = "yfinance",
    start: date | None = None,
    end: date | None = None,
    limit: LimitParam = 100,
    cursor: str | None = None,
) -> OhlcvPage:
    """List OHLCV bars for one asset/source with keyset cursor pagination.

    Ordering is ``(time, source)`` ascending, so paging across cursors is
    stable — no duplicate or missing rows even under concurrent inserts.
    Only the specified ``asset_id``/``source``/``[start, end]`` window is
    returned; ``end`` is inclusive. An asset with no matching bars yields an
    empty ``items`` list with ``next_cursor=None`` and ``has_more=False``.
    """
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset {asset_id} not found.",
        )

    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start must be <= end",
        )

    stmt = select(Ohlcv).where(Ohlcv.asset_id == asset_id, Ohlcv.source == source)

    if start is not None:
        stmt = stmt.where(Ohlcv.time >= datetime(start.year, start.month, start.day, tzinfo=UTC))
    if end is not None:
        # end-day inclusive => [start, end+1day)
        stmt = stmt.where(
            Ohlcv.time < datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
        )

    if cursor is not None:
        ct, cs = _decode_cursor(cursor)
        stmt = stmt.where(tuple_(Ohlcv.time, Ohlcv.source) > [ct, cs])

    stmt = stmt.order_by(Ohlcv.time, Ohlcv.source).limit(limit + 1)
    rows = list(db.scalars(stmt))

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = _encode_cursor(items[-1]) if has_more and items else None

    return OhlcvPage(items=items, next_cursor=next_cursor, has_more=has_more)
