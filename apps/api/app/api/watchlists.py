"""Watchlist CRUD + asset membership router.

Endpoints
---------
- ``GET    /watchlists``                                 list own watchlists (+items)
- ``POST   /watchlists``                                 create a named watchlist
- ``DELETE /watchlists/{watchlist_id}``                  delete own watchlist (+items)
- ``POST   /watchlists/{watchlist_id}/assets/{asset_id}``  add asset (idempotent)
- ``DELETE /watchlists/{watchlist_id}/assets/{asset_id}``  remove asset (idempotent)

Notes
-----
All endpoints require a valid bearer token (``get_current_user``). Ownership
is enforced server-side: every watchlist lookup is scoped to the caller's
``user_id``, so a watchlist that belongs to another user is indistinguishable
from one that does not exist (both yield ``404``, never ``403`` — no resource
existence leak).

The ``watchlist_items`` foreign keys carry no ``ON DELETE CASCADE`` (FRA-5),
so removing a watchlist must first delete its items explicitly. Adding an
asset that is already a member is idempotent (no error, no duplicate row);
removing a non-member is likewise idempotent.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models.asset import Asset
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem
from app.schemas.watchlist import WatchlistCreate, WatchlistItemRead, WatchlistRead

router = APIRouter(prefix="/watchlists", tags=["watchlists"])

# Dependency aliases — Annotated keeps defaults free of call expressions
# (satisfies ruff B008) and reads cleanly at the handler signature.
DBSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _get_owned_watchlist(db: Session, watchlist_id: uuid.UUID, user_id: uuid.UUID) -> Watchlist:
    """Fetch a watchlist scoped to ``user_id`` or raise a uniform 404.

    Scoping on ``user_id`` collapses the two failure cases — "does not exist"
    and "belongs to someone else" — into a single indistinguishable 404 so
    callers cannot probe for other users' watchlist ids.
    """
    watchlist = db.scalar(
        select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user_id)
    )
    if watchlist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watchlist not found.",
        )
    return watchlist


def _build_watchlist_read(db: Session, watchlist: Watchlist) -> WatchlistRead:
    """Assemble a ``WatchlistRead`` with items hydrated from a joined query."""
    rows = db.execute(
        select(WatchlistItem, Asset)
        .join(Asset, WatchlistItem.asset_id == Asset.id)
        .where(WatchlistItem.watchlist_id == watchlist.id)
        .order_by(WatchlistItem.added_at, WatchlistItem.asset_id)
    ).all()
    items = [
        WatchlistItemRead(
            asset_id=item.asset_id,
            symbol=asset.symbol,
            exchange=asset.exchange,
            name=asset.name,
            data_source=asset.data_source,
            added_at=item.added_at,
        )
        for item, asset in rows
    ]
    return WatchlistRead(
        id=watchlist.id,
        name=watchlist.name,
        created_at=watchlist.created_at,
        items=items,
    )


@router.get(
    "",
    response_model=list[WatchlistRead],
    response_model_by_alias=True,
    summary="List the current user's watchlists",
)
def list_watchlists(db: DBSession, current_user: CurrentUser) -> list[WatchlistRead]:
    """Return every watchlist owned by the caller, each with its members."""
    watchlists = list(
        db.scalars(
            select(Watchlist)
            .where(Watchlist.user_id == current_user.id)
            .order_by(Watchlist.created_at)
        )
    )
    return [_build_watchlist_read(db, wl) for wl in watchlists]


@router.post(
    "",
    response_model=WatchlistRead,
    status_code=status.HTTP_201_CREATED,
    response_model_by_alias=True,
    summary="Create a watchlist",
)
def create_watchlist(
    payload: WatchlistCreate, db: DBSession, current_user: CurrentUser
) -> WatchlistRead:
    """Create a named watchlist for the caller.

    The name is trimmed by the schema (``str_strip_whitespace=True``); a name
    that trims to empty fails Pydantic validation (422). A watchlist with the
    same name already owned by this user yields ``409 Conflict``.
    """
    name = payload.name.strip()
    if not name:
        # Defensive guard — str_strip_whitespace + min_length already reject
        # this at the schema layer, but keep the handler explicit.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Watchlist name must not be empty.",
        )

    existing = db.scalar(
        select(Watchlist).where(
            Watchlist.user_id == current_user.id,
            Watchlist.name == name,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Watchlist named {name!r} already exists.",
        )

    watchlist = Watchlist(user_id=current_user.id, name=name)
    db.add(watchlist)
    db.commit()
    db.refresh(watchlist)
    return _build_watchlist_read(db, watchlist)


@router.delete(
    "/{watchlist_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a watchlist and its items",
)
def delete_watchlist(
    watchlist_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
) -> None:
    """Delete the caller's watchlist and every item it contains.

    ``watchlist_items`` has no ``ON DELETE CASCADE`` (FRA-5), so items are
    removed first. A watchlist owned by another user returns 404, not 403.
    """
    watchlist = _get_owned_watchlist(db, watchlist_id, current_user.id)
    db.execute(delete(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist.id))
    db.delete(watchlist)
    db.commit()


@router.post(
    "/{watchlist_id}/assets/{asset_id}",
    response_model=WatchlistRead,
    response_model_by_alias=True,
    summary="Add an asset to a watchlist (idempotent)",
)
def add_asset_to_watchlist(
    watchlist_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
) -> WatchlistRead:
    """Add ``asset_id`` to the caller's watchlist.

    Adding an asset that is already a member is idempotent: no error, no
    duplicate row, the existing membership is left untouched. A watchlist
    owned by another user returns 404; a non-existent ``asset_id`` returns 404.
    """
    watchlist = _get_owned_watchlist(db, watchlist_id, current_user.id)

    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset {asset_id} not found.",
        )

    existing = db.scalar(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist.id,
            WatchlistItem.asset_id == asset_id,
        )
    )
    if existing is None:
        db.add(WatchlistItem(watchlist_id=watchlist.id, asset_id=asset_id))
        db.commit()
        db.refresh(watchlist)

    return _build_watchlist_read(db, watchlist)


@router.delete(
    "/{watchlist_id}/assets/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an asset from a watchlist (idempotent)",
)
def remove_asset_from_watchlist(
    watchlist_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
) -> None:
    """Remove ``asset_id`` from the caller's watchlist.

    Removing an asset that is not a member (or whose watchlist has no such
    item) is idempotent: no error is raised. A watchlist owned by another
    user returns 404.
    """
    # Resolve ownership first — a non-owned watchlist is 404 even if the
    # asset_id would otherwise be a no-op.
    watchlist = _get_owned_watchlist(db, watchlist_id, current_user.id)
    db.execute(
        delete(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist.id,
            WatchlistItem.asset_id == asset_id,
        )
    )
    db.commit()
