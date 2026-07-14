"""Real-DB tests for the idempotent asset seed (FRA-21).

Verifies ``app.db.seed.seed_assets`` is idempotent: the first call inserts
the universe, the second call updates every row (no duplicates), and a
changed name is reflected on re-seed. Uses the shared host Postgres and
surgical cleanup keyed off the ``FRA21TEST`` symbol prefix so the real
``UNIVERSE`` is never touched.

Self-contained — mirrors the pattern in ``test_ohlcv_ingestion.py``.
``tests/conftest.py`` is left untouched (it already sets a localhost
DATABASE_URL fallback for the host dev environment).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.db import seed as seed_mod
from app.db.session import SessionLocal
from app.models.asset import Asset
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

TEST_PREFIX = "FRA21TEST"

# Test-only universe: small, every asset type/currency represented, all
# symbols prefixed so they can't collide with the real UNIVERSE rows.
TEST_UNIVERSE: list[dict] = [
    {
        "symbol": f"{TEST_PREFIX}-STK",
        "exchange": "NASDAQ",
        "name": "Test Stock Mk1",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": f"{TEST_PREFIX}-ETF",
        "exchange": "AMEX",
        "name": "Test ETF Mk1",
        "asset_type": "etf",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": f"{TEST_PREFIX}-CN",
        "exchange": "SSE",
        "name": "测试股票一",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
]


def _cleanup(db: Session) -> None:
    """Delete only rows owned by this suite."""
    db.execute(text("DELETE FROM assets WHERE symbol LIKE :p"), {"p": f"{TEST_PREFIX}%"})
    db.commit()


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)
        db.close()


@pytest.fixture()
def patched_universe(monkeypatch) -> list[dict]:
    """Replace the real UNIVERSE with the small test set."""
    monkeypatch.setattr(seed_mod, "UNIVERSE", TEST_UNIVERSE)
    return TEST_UNIVERSE


def _count_assets(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(Asset).where(Asset.symbol.like(f"{TEST_PREFIX}%"))
        )
        or 0
    )


def test_seed_inserts_all_rows_first_run(db_session: Session, patched_universe: list[dict]) -> None:
    inserted, updated = seed_mod.seed_assets(db_session)

    assert inserted == len(patched_universe)
    assert updated == 0
    assert _count_assets(db_session) == len(patched_universe)


def test_seed_is_idempotent_second_run_updates_all(
    db_session: Session, patched_universe: list[dict]
) -> None:
    ins1, upd1 = seed_mod.seed_assets(db_session)
    ins2, upd2 = seed_mod.seed_assets(db_session)

    assert (ins1, upd1) == (len(patched_universe), 0)
    assert (ins2, upd2) == (0, len(patched_universe))
    # No duplicate rows — row count stays at universe size.
    assert _count_assets(db_session) == len(patched_universe)


def test_seed_updates_name_on_conflict(db_session: Session, patched_universe: list[dict]) -> None:
    seed_mod.seed_assets(db_session)

    # Re-seed with a changed name for the stock row; everything else identical.
    revised = [
        {
            **r,
            "name": r["name"].replace("Mk1", "Mk2")
            if r["name"].startswith("Test ")
            else r["name"] + "改",
        }
        for r in patched_universe
    ]
    patched_universe[:] = revised  # mutate the same list the module now points at
    inserted, updated = seed_mod.seed_assets(db_session)

    assert inserted == 0
    assert updated == len(revised)
    assert _count_assets(db_session) == len(revised)

    stk = db_session.scalar(select(Asset).where(Asset.symbol == f"{TEST_PREFIX}-STK"))
    cn = db_session.scalar(select(Asset).where(Asset.symbol == f"{TEST_PREFIX}-CN"))
    assert stk is not None and stk.name.endswith("Mk2")
    assert cn is not None and cn.name.endswith("改")


def test_seed_empty_universe_is_noop(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(seed_mod, "UNIVERSE", [])
    assert seed_mod.seed_assets(db_session) == (0, 0)
    assert _count_assets(db_session) == 0


def test_seed_dedups_duplicate_symbol_exchange(db_session: Session, monkeypatch) -> None:
    """A single INSERT … ON CONFLICT DO UPDATE can't target one row twice
    (Postgres raises CardinalityViolation); ``_upsert_assets`` dedups on
    ``(symbol, exchange)`` first. Two rows sharing a key collapse to one row,
    with the last occurrence winning (mirrors the active-then-delisted feed
    ordering where a later lower-priority feed overrides).
    """
    dup_universe = [
        {
            "symbol": f"{TEST_PREFIX}-DUP",
            "exchange": "NASDAQ",
            "name": "First",
            "asset_type": "stock",
            "currency": "USD",
            "data_source": "yfinance",
        },
        {
            "symbol": f"{TEST_PREFIX}-DUP",
            "exchange": "NASDAQ",
            "name": "Second",
            "asset_type": "stock",
            "currency": "USD",
            "data_source": "yfinance",
        },
    ]
    monkeypatch.setattr(seed_mod, "UNIVERSE", dup_universe)

    inserted, updated = seed_mod.seed_assets(db_session)
    assert inserted == 1  # deduped to a single row
    assert updated == 0

    rows = list(db_session.scalars(select(Asset).where(Asset.symbol == f"{TEST_PREFIX}-DUP")))
    assert len(rows) == 1
    assert rows[0].name == "Second"  # last occurrence wins
