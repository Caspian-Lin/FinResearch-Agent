"""Idempotent OHLCV upsert via PostgreSQL ON CONFLICT."""

from __future__ import annotations

import uuid

from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.ohlcv import Ohlcv
from app.services.yfinance import OhlcvBar


def upsert_ohlcv_bars(
    db: Session, asset_id: uuid.UUID, source: str, bars: list[OhlcvBar]
) -> tuple[int, int]:
    """幂等写入 OHLCV bars,返回 (inserted, updated)。

    使用 ``ON CONFLICT (asset_id, time, source) DO UPDATE``。``xmax = 0``
    trick 区分本次新插入与已存在被更新的行。重复同步不产生重复行,
    已有窗口的修订数据会被覆盖更新。本函数不 commit —— 调用方控制事务。
    """
    if not bars:
        return (0, 0)
    rows = [
        {
            "asset_id": asset_id,
            "source": source,
            "time": b.time,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "adjusted_close": b.adjusted_close,
            "volume": b.volume,
        }
        for b in bars
    ]
    stmt = pg_insert(Ohlcv).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["asset_id", "time", "source"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "adjusted_close": stmt.excluded.adjusted_close,
            "volume": stmt.excluded.volume,
        },
    ).returning(literal_column("(xmax = 0)").label("inserted"))
    result = db.execute(stmt)
    flags = [row.inserted for row in result]
    inserted = sum(1 for f in flags if f)
    updated = len(flags) - inserted
    return (inserted, updated)
