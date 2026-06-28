"""Idempotent asset metadata seed — static reference set + dynamic full market.

Two complementary entry points, both invoked manually via ``make seed``
(``python -m app.db.seed``) and not coupled to backend startup:

* :func:`seed_assets` — the FRA-21 static :data:`UNIVERSE` (~50 reference
  instruments in the FRA-78 unified symbol convention). Offline-friendly,
  CI-safe, and the historical bootstrap path.
* :func:`seed_from_akshare` — the FRA-79 dynamic full-market pull via the
  AkShare universe fetchers (~24k instruments across A/HK/US plus the
  terminated-listing boards). ``make seed`` / :func:`main` use this by
  default so newly listed and delisted instruments are picked up live.

Only metadata (symbol/exchange/name/asset_type/currency/data_source/
list_status) is seeded here. Price history (OHLCV) is synced on demand per
asset, never by this script.

Both paths upsert idempotently via ``ON CONFLICT (symbol, exchange)
DO UPDATE`` and report inserted-vs-updated counts using the ``xmax = 0``
trick (same pattern as the OHLCV upsert in ``app/services/ohlcv.py``). No
rows are duplicated. The dynamic path upserts the ``active`` universe first,
then ``delisted``, so a delisted flag wins on conflict.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, engine
from app.models.asset import Asset

# akshare_universe imports no AkShare library at module top (each fetcher
# lazy-imports it), so this module-level import stays cheap and does not pull
# in the optional dependency — only actually calling the fetchers does.
from app.services.datasources.akshare_universe import AssetSpec, fetch_all_universes

# Sample universe (~50 instruments), FRA-78 unified symbol convention.
# Every symbol carries an exchange suffix so it round-trips unambiguously
# across data sources:
# - US large-caps: NASDAQ ``.O`` / NYSE ``.N``, USD
# - US ETFs: AMEX ``.A``, USD
# - A-share blue chips: SSE ``.SH`` / SZSE ``.SZ``, CNY (legacy ``.SS`` is no
#   longer used — FRA-78 standardized SSE to ``.SH``); name is the Chinese
#   company name.
# ``data_source`` records each asset's preferred *bar* source (FRA-83):
# everything → ``yfinance``. A-share bars are pulled via yfinance (``.SS``/
# ``.SZ``) because akshare's ``stock_zh_a_hist`` is rate-limited and returns
# empty in practice (verified: ``sh601398`` → ``shape (0,0)``), while yfinance
# is verified working (``601398.SS`` → 9 bars); akshare is used only to *list*
# A-shares (see ``akshare_universe.py``), not to fetch their bars.
# The Asset model does NOT normalize symbol/exchange to upper case, so the
# values below are stored as-is. US symbols are already upper-case; A-share
# symbols keep their ``.SH``/``.SZ`` suffix exactly.
UNIVERSE: list[dict] = [
    # ---------- US large-cap stocks ----------
    {
        "symbol": "AAPL.O",
        "exchange": "NASDAQ",
        "name": "Apple Inc.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "MSFT.O",
        "exchange": "NASDAQ",
        "name": "Microsoft Corporation",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "GOOGL.O",
        "exchange": "NASDAQ",
        "name": "Alphabet Inc.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "AMZN.O",
        "exchange": "NASDAQ",
        "name": "Amazon.com, Inc.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "NVDA.O",
        "exchange": "NASDAQ",
        "name": "NVIDIA Corporation",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "META.O",
        "exchange": "NASDAQ",
        "name": "Meta Platforms, Inc.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "TSLA.O",
        "exchange": "NASDAQ",
        "name": "Tesla, Inc.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "AVGO.O",
        "exchange": "NASDAQ",
        "name": "Broadcom Inc.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "PEP.O",
        "exchange": "NASDAQ",
        "name": "PepsiCo, Inc.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "COST.O",
        "exchange": "NASDAQ",
        "name": "Costco Wholesale Corporation",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "NFLX.O",
        "exchange": "NASDAQ",
        "name": "Netflix, Inc.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "AMD.O",
        "exchange": "NASDAQ",
        "name": "Advanced Micro Devices, Inc.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "INTC.O",
        "exchange": "NASDAQ",
        "name": "Intel Corporation",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "JPM.N",
        "exchange": "NYSE",
        "name": "JPMorgan Chase & Co.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "V.N",
        "exchange": "NYSE",
        "name": "Visa Inc.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "JNJ.N",
        "exchange": "NYSE",
        "name": "Johnson & Johnson",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "WMT.N",
        "exchange": "NYSE",
        "name": "Walmart Inc.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "PG.N",
        "exchange": "NYSE",
        "name": "Procter & Gamble Company",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "MA.N",
        "exchange": "NYSE",
        "name": "Mastercard Incorporated",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "HD.N",
        "exchange": "NYSE",
        "name": "The Home Depot, Inc.",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "KO.N",
        "exchange": "NYSE",
        "name": "The Coca-Cola Company",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "DIS.N",
        "exchange": "NYSE",
        "name": "The Walt Disney Company",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "BAC.N",
        "exchange": "NYSE",
        "name": "Bank of America Corporation",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "XOM.N",
        "exchange": "NYSE",
        "name": "Exxon Mobil Corporation",
        "asset_type": "stock",
        "currency": "USD",
        "data_source": "yfinance",
    },
    # ---------- US ETFs ----------
    {
        "symbol": "SPY.A",
        "exchange": "AMEX",
        "name": "SPDR S&P 500 ETF Trust",
        "asset_type": "etf",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "QQQ.A",
        "exchange": "AMEX",
        "name": "Invesco QQQ Trust (Nasdaq 100)",
        "asset_type": "etf",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "DIA.A",
        "exchange": "AMEX",
        "name": "SPDR Dow Jones Industrial Average ETF",
        "asset_type": "etf",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "IWM.A",
        "exchange": "AMEX",
        "name": "iShares Russell 2000 ETF",
        "asset_type": "etf",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "VOO.A",
        "exchange": "AMEX",
        "name": "Vanguard S&P 500 ETF",
        "asset_type": "etf",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "VTI.A",
        "exchange": "AMEX",
        "name": "Vanguard Total Stock Market ETF",
        "asset_type": "etf",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "EEM.A",
        "exchange": "AMEX",
        "name": "iShares MSCI Emerging Markets ETF",
        "asset_type": "etf",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "XLK.A",
        "exchange": "AMEX",
        "name": "Technology Select Sector SPDR ETF",
        "asset_type": "etf",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "XLF.A",
        "exchange": "AMEX",
        "name": "Financial Select Sector SPDR ETF",
        "asset_type": "etf",
        "currency": "USD",
        "data_source": "yfinance",
    },
    {
        "symbol": "XLE.A",
        "exchange": "AMEX",
        "name": "Energy Select Sector SPDR ETF",
        "asset_type": "etf",
        "currency": "USD",
        "data_source": "yfinance",
    },
    # ---------- A-share blue chips ----------
    {
        "symbol": "600519.SH",
        "exchange": "SSE",
        "name": "贵州茅台",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
    {
        "symbol": "601318.SH",
        "exchange": "SSE",
        "name": "中国平安",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
    {
        "symbol": "600036.SH",
        "exchange": "SSE",
        "name": "招商银行",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
    {
        "symbol": "601398.SH",
        "exchange": "SSE",
        "name": "工商银行",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
    {
        "symbol": "600276.SH",
        "exchange": "SSE",
        "name": "恒瑞医药",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
    {
        "symbol": "601012.SH",
        "exchange": "SSE",
        "name": "隆基绿能",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
    {
        "symbol": "000001.SZ",
        "exchange": "SZSE",
        "name": "平安银行",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
    {
        "symbol": "000858.SZ",
        "exchange": "SZSE",
        "name": "五粮液",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
    {
        "symbol": "300750.SZ",
        "exchange": "SZSE",
        "name": "宁德时代",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
    {
        "symbol": "000333.SZ",
        "exchange": "SZSE",
        "name": "美的集团",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
    {
        "symbol": "002594.SZ",
        "exchange": "SZSE",
        "name": "比亚迪",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
    {
        "symbol": "000651.SZ",
        "exchange": "SZSE",
        "name": "格力电器",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
    {
        "symbol": "002475.SZ",
        "exchange": "SZSE",
        "name": "立讯精密",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "yfinance",
    },
]


def _rows_from_dicts(records: Iterable[dict]) -> list[dict]:
    """Coerce seed dicts (the :data:`UNIVERSE` shape) to full upsert rows.

    Each input dict carries the metadata columns; ``list_status`` is filled
    with the model default ``'active'`` when absent so the static universe and
    the dynamic specs share one upsert path.
    """
    return [
        {
            "symbol": r["symbol"],
            "exchange": r["exchange"],
            "name": r["name"],
            "asset_type": r["asset_type"],
            "currency": r["currency"],
            "data_source": r["data_source"],
            "list_status": r.get("list_status", "active"),
        }
        for r in records
    ]


# Each row binds 7 params; Postgres caps a single statement at 65535 bind
# params, so one giant INSERT for the full market (~24k rows) overflows it.
# Upsert in chunks well under the ceiling and accumulate counts across them.
_UPSERT_CHUNK = 4000


def _upsert_assets(db: Session, rows: list[dict]) -> tuple[int, int]:
    """Upsert asset ``rows`` on ``(symbol, exchange)``; return ``(inserted, updated)``.

    On conflict every mutable column — including ``list_status`` — is
    refreshed from the incoming row, so re-seeds (static or dynamic) keep the
    table in sync with the source. ``xmax = 0`` distinguishes inserts from
    updates (an updated row's xmax holds the updating xact id). Rows are
    chunked (see :data:`_UPSERT_CHUNK`) to stay under Postgres' 65535 bind
    param ceiling; counts accumulate across chunks. Commits once at the end.
    """
    if not rows:
        return (0, 0)

    # Collapse duplicate (symbol, exchange) keys first: a single
    # INSERT … ON CONFLICT DO UPDATE statement cannot target the same row
    # twice (Postgres raises CardinalityViolation), and the source feeds can
    # emit repeats (e.g. a delisted code on both SZ/SH boards' overlap, or a
    # re-listed code). Keep the last occurrence so later/lower-priority feeds
    # win — matching the active-then-delisted ordering of seed_from_akshare.
    deduped: dict[tuple[str, str], dict] = {}
    for r in rows:
        deduped[(r["symbol"], r["exchange"])] = r
    unique_rows = list(deduped.values())

    inserted = 0
    updated = 0
    for start in range(0, len(unique_rows), _UPSERT_CHUNK):
        batch = unique_rows[start : start + _UPSERT_CHUNK]
        stmt = pg_insert(Asset).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Asset.symbol, Asset.exchange],
            set_={
                "name": stmt.excluded.name,
                "asset_type": stmt.excluded.asset_type,
                "currency": stmt.excluded.currency,
                "data_source": stmt.excluded.data_source,
                "list_status": stmt.excluded.list_status,
            },
        ).returning(literal_column("(xmax = 0)").label("inserted"))
        result = db.execute(stmt)
        flags = [row.inserted for row in result]
        ins = sum(1 for f in flags if f)
        inserted += ins
        updated += len(flags) - ins
    db.commit()
    return (inserted, updated)


def seed_assets(db: Session) -> tuple[int, int]:
    """Upsert the static :data:`UNIVERSE`; return ``(inserted, updated)``.

    The FRA-21 reference set in FRA-78 unified-symbol form. Idempotent and
    offline-friendly — no AkShare dependency. Kept as the CI-safe bootstrap
    path and a fallback for :func:`seed_from_akshare`.
    """
    return _upsert_assets(db, _rows_from_dicts(UNIVERSE))


def seed_from_akshare(db: Session) -> dict[str, tuple[int, int]]:
    """Upsert the dynamic full-market universe via AkShare (FRA-79).

    Pulls the three live markets + the terminated-listing boards
    (:func:`app.services.datasources.akshare_universe.fetch_all_universes`),
    upserts the ``active`` universe first, then ``delisted`` so a delisted
    flag wins on a ``(symbol, exchange)`` conflict. Returns per-group
    ``(inserted, updated)`` counts.
    """
    active_specs, delisted_specs = fetch_all_universes()
    counts = {
        "active": _upsert_assets(db, [_spec_to_row(s) for s in active_specs]),
        "delisted": _upsert_assets(db, [_spec_to_row(s) for s in delisted_specs]),
    }
    return counts


def _spec_to_row(spec: AssetSpec) -> dict:
    """Flatten an :class:`AssetSpec` into the upsert row shape."""
    return {
        "symbol": spec.symbol,
        "exchange": spec.exchange,
        "name": spec.name,
        "asset_type": spec.asset_type,
        "currency": spec.currency,
        "data_source": spec.data_source,
        "list_status": spec.list_status,
    }


def main() -> None:
    """Run the dynamic AkShare seed and print a per-group summary."""
    db = SessionLocal()
    try:
        counts = seed_from_akshare(db)
        (ins_a, upd_a) = counts["active"]
        (ins_d, upd_d) = counts["delisted"]
        print(
            "Seeded from AkShare — "
            f"active {ins_a} inserted / {upd_a} updated, "
            f"delisted {ins_d} inserted / {upd_d} updated "
            f"(total {ins_a + ins_d} new, {upd_a + upd_d} updated)"
        )
    finally:
        db.close()
        engine.dispose()  # close the pool so the one-shot CLI exits clean


if __name__ == "__main__":
    main()
