"""Asset CRUD router.

Endpoints
---------
- ``POST /assets``            create (normalizes symbol/exchange to UPPER)
- ``GET  /assets``            list with optional filters + stable pagination
- ``GET  /assets/{asset_id}`` fetch by UUID (404 when missing)

Notes
-----
Identity is the surrogate UUID ``asset_id``. ``symbol`` is *not* globally
unique — the same ticker can trade on multiple exchanges — so uniqueness is
enforced on ``(symbol, exchange)``. There is intentionally no
``GET /assets/{symbol}`` route.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.asset import Asset
from app.schemas.asset import AssetCreate, AssetPage, AssetRead

router = APIRouter(prefix="/assets", tags=["assets"])

# Dependency aliases — using Annotated keeps defaults free of call expressions
# (satisfies ruff B008) and reads cleanly at the handler signature.
DBSession = Annotated[Session, Depends(get_db)]
LimitParam = Annotated[int, Query(ge=1, le=500)]
OffsetParam = Annotated[int, Query(ge=0)]
SymbolParam = Annotated[str | None, Query(description="Exact symbol match (case-insensitive)")]
ExchangeParam = Annotated[str | None, Query(description="Exact exchange match (case-insensitive)")]
NameParam = Annotated[str | None, Query(description="Case-insensitive partial match on asset name")]
SourceParam = Annotated[
    str | None, Query(description="Exact data_source match (yfinance/akshare/tushare)")
]
ExchangesParam = Annotated[
    list[str] | None, Query(description="Multi-select exchange match (any of)")
]
KeywordParam = Annotated[
    str | None, Query(description="Case-insensitive partial match on symbol OR name")
]


def _normalize_symbol(value: str) -> str:
    return value.strip().upper()


def _normalize_exchange(value: str) -> str:
    return value.strip().upper()


@router.post(
    "",
    response_model=AssetRead,
    status_code=status.HTTP_201_CREATED,
    response_model_by_alias=True,
    summary="Create an asset",
)
def create_asset(payload: AssetCreate, db: DBSession) -> Asset:
    """Create a new asset.

    Symbol and exchange are normalized (trimmed, upper-cased) before insert.
    A pre-existing ``(symbol, exchange)`` pair yields ``409 Conflict`` and no
    row is written.
    """
    symbol = _normalize_symbol(payload.symbol)
    exchange = _normalize_exchange(payload.exchange)

    existing = db.scalar(select(Asset).where(Asset.symbol == symbol, Asset.exchange == exchange))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Asset ({symbol}, {exchange}) already exists.",
        )

    asset = Asset(
        symbol=symbol,
        name=payload.name.strip(),
        exchange=exchange,
        asset_type=payload.asset_type.strip(),
        currency=payload.currency.strip().upper(),
    )
    db.add(asset)
    try:
        db.commit()
    except IntegrityError as exc:
        # Race: another request inserted the same (symbol, exchange) first.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Asset ({symbol}, {exchange}) already exists.",
        ) from exc
    db.refresh(asset)
    return asset


@router.get(
    "",
    response_model=AssetPage,
    response_model_by_alias=True,
    summary="List assets (filter + paginate)",
)
def list_assets(
    db: DBSession,
    symbol: SymbolParam = None,
    exchange: ExchangeParam = None,
    name: NameParam = None,
    source: SourceParam = None,
    exchanges: ExchangesParam = None,
    keyword: KeywordParam = None,
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
) -> dict[str, object]:
    """List assets with optional filters and stable pagination.

    Filters compose with AND:

    * ``symbol`` / ``exchange`` — exact, case-insensitive (legacy params).
    * ``exchanges`` — multi-select exchange match (any of the set), for the
      frontend's exchange multi-picker.
    * ``name`` — case-insensitive partial match on the asset name.
    * ``source`` — exact ``data_source`` match (yfinance/akshare/tushare).
    * ``keyword`` — case-insensitive partial match on symbol *or* name, for
      the frontend's single "code or name" search box.

    Ordering is deterministic ``(symbol, exchange, id)`` so paging is stable.
    """
    stmt = select(Asset).order_by(Asset.symbol, Asset.exchange, Asset.id)
    count_stmt = select(func.count()).select_from(Asset)

    conditions = []
    if symbol is not None:
        conditions.append(Asset.symbol == _normalize_symbol(symbol))
    if exchange is not None:
        conditions.append(Asset.exchange == _normalize_exchange(exchange))
    if exchanges:
        conditions.append(Asset.exchange.in_([_normalize_exchange(e) for e in exchanges]))
    if name is not None:
        conditions.append(Asset.name.ilike(f"%{name}%"))
    if source is not None:
        conditions.append(Asset.data_source == source.strip().lower())
    if keyword is not None:
        conditions.append(or_(Asset.symbol.ilike(f"%{keyword}%"), Asset.name.ilike(f"%{keyword}%")))

    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

    total = int(db.scalar(count_stmt) or 0)
    items = list(db.scalars(stmt.limit(limit).offset(offset)).unique())
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/{asset_id}",
    response_model=AssetRead,
    response_model_by_alias=True,
    summary="Get an asset by UUID",
)
def get_asset(asset_id: uuid.UUID, db: DBSession) -> Asset:
    """Fetch a single asset by its surrogate UUID.

    Returns ``404`` when no asset matches ``asset_id``.
    """
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset {asset_id} not found.",
        )
    return asset
