"""Idempotent asset metadata seed for the Week 1 sample universe.

One-shot, manually invoked via ``make seed`` (``python -m app.db.seed``).
Not coupled to backend startup — run once to populate the database with
~50 reference instruments (US large-caps, US ETFs, A-share blue chips).

Only metadata (symbol/exchange/name/asset_type/currency) is seeded here.
Price history (OHLCV) is synced on demand per asset, never by this script.

The seed is idempotent: re-running it upserts every row via
``ON CONFLICT (symbol, exchange) DO UPDATE`` and reports inserted vs
updated counts using the ``xmax = 0`` trick (same pattern as the OHLCV
upsert in ``app/services/ohlcv.py``). No rows are duplicated.
"""

from __future__ import annotations

from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.asset import Asset

# Sample universe (~50 instruments).
# - US large-caps: NASDAQ / NYSE, USD
# - US ETFs: AMEX, USD
# - A-share blue chips: SSE (.SS) / SZSE (.SZ), CNY; symbol carries the
#   yfinance suffix verbatim (e.g. ``600519.SS``); name is the Chinese
#   company name.
# The Asset model does NOT normalize symbol/exchange to upper case, so the
# values below are stored as-is. US symbols are already upper-case; A-share
# symbols keep their ``.SS``/``.SZ`` suffix exactly.
UNIVERSE: list[dict] = [
    # ---------- US large-cap stocks ----------
    {
        "symbol": "AAPL",
        "exchange": "NASDAQ",
        "name": "Apple Inc.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "MSFT",
        "exchange": "NASDAQ",
        "name": "Microsoft Corporation",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "GOOGL",
        "exchange": "NASDAQ",
        "name": "Alphabet Inc.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "AMZN",
        "exchange": "NASDAQ",
        "name": "Amazon.com, Inc.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "NVDA",
        "exchange": "NASDAQ",
        "name": "NVIDIA Corporation",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "META",
        "exchange": "NASDAQ",
        "name": "Meta Platforms, Inc.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "TSLA",
        "exchange": "NASDAQ",
        "name": "Tesla, Inc.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "AVGO",
        "exchange": "NASDAQ",
        "name": "Broadcom Inc.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "PEP",
        "exchange": "NASDAQ",
        "name": "PepsiCo, Inc.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "COST",
        "exchange": "NASDAQ",
        "name": "Costco Wholesale Corporation",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "NFLX",
        "exchange": "NASDAQ",
        "name": "Netflix, Inc.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "AMD",
        "exchange": "NASDAQ",
        "name": "Advanced Micro Devices, Inc.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "INTC",
        "exchange": "NASDAQ",
        "name": "Intel Corporation",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "JPM",
        "exchange": "NYSE",
        "name": "JPMorgan Chase & Co.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "V",
        "exchange": "NYSE",
        "name": "Visa Inc.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "JNJ",
        "exchange": "NYSE",
        "name": "Johnson & Johnson",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "WMT",
        "exchange": "NYSE",
        "name": "Walmart Inc.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "PG",
        "exchange": "NYSE",
        "name": "Procter & Gamble Company",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "MA",
        "exchange": "NYSE",
        "name": "Mastercard Incorporated",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "HD",
        "exchange": "NYSE",
        "name": "The Home Depot, Inc.",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "KO",
        "exchange": "NYSE",
        "name": "The Coca-Cola Company",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "DIS",
        "exchange": "NYSE",
        "name": "The Walt Disney Company",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "BAC",
        "exchange": "NYSE",
        "name": "Bank of America Corporation",
        "asset_type": "stock",
        "currency": "USD",
    },
    {
        "symbol": "XOM",
        "exchange": "NYSE",
        "name": "Exxon Mobil Corporation",
        "asset_type": "stock",
        "currency": "USD",
    },
    # ---------- US ETFs ----------
    {
        "symbol": "SPY",
        "exchange": "AMEX",
        "name": "SPDR S&P 500 ETF Trust",
        "asset_type": "etf",
        "currency": "USD",
    },
    {
        "symbol": "QQQ",
        "exchange": "AMEX",
        "name": "Invesco QQQ Trust (Nasdaq 100)",
        "asset_type": "etf",
        "currency": "USD",
    },
    {
        "symbol": "DIA",
        "exchange": "AMEX",
        "name": "SPDR Dow Jones Industrial Average ETF",
        "asset_type": "etf",
        "currency": "USD",
    },
    {
        "symbol": "IWM",
        "exchange": "AMEX",
        "name": "iShares Russell 2000 ETF",
        "asset_type": "etf",
        "currency": "USD",
    },
    {
        "symbol": "VOO",
        "exchange": "AMEX",
        "name": "Vanguard S&P 500 ETF",
        "asset_type": "etf",
        "currency": "USD",
    },
    {
        "symbol": "VTI",
        "exchange": "AMEX",
        "name": "Vanguard Total Stock Market ETF",
        "asset_type": "etf",
        "currency": "USD",
    },
    {
        "symbol": "EEM",
        "exchange": "AMEX",
        "name": "iShares MSCI Emerging Markets ETF",
        "asset_type": "etf",
        "currency": "USD",
    },
    {
        "symbol": "XLK",
        "exchange": "AMEX",
        "name": "Technology Select Sector SPDR ETF",
        "asset_type": "etf",
        "currency": "USD",
    },
    {
        "symbol": "XLF",
        "exchange": "AMEX",
        "name": "Financial Select Sector SPDR ETF",
        "asset_type": "etf",
        "currency": "USD",
    },
    {
        "symbol": "XLE",
        "exchange": "AMEX",
        "name": "Energy Select Sector SPDR ETF",
        "asset_type": "etf",
        "currency": "USD",
    },
    # ---------- A-share blue chips ----------
    {
        "symbol": "600519.SS",
        "exchange": "SSE",
        "name": "贵州茅台",
        "asset_type": "stock",
        "currency": "CNY",
    },
    {
        "symbol": "601318.SS",
        "exchange": "SSE",
        "name": "中国平安",
        "asset_type": "stock",
        "currency": "CNY",
    },
    {
        "symbol": "600036.SS",
        "exchange": "SSE",
        "name": "招商银行",
        "asset_type": "stock",
        "currency": "CNY",
    },
    {
        "symbol": "601398.SS",
        "exchange": "SSE",
        "name": "工商银行",
        "asset_type": "stock",
        "currency": "CNY",
    },
    {
        "symbol": "600276.SS",
        "exchange": "SSE",
        "name": "恒瑞医药",
        "asset_type": "stock",
        "currency": "CNY",
    },
    {
        "symbol": "601012.SS",
        "exchange": "SSE",
        "name": "隆基绿能",
        "asset_type": "stock",
        "currency": "CNY",
    },
    {
        "symbol": "000001.SZ",
        "exchange": "SZSE",
        "name": "平安银行",
        "asset_type": "stock",
        "currency": "CNY",
    },
    {
        "symbol": "000858.SZ",
        "exchange": "SZSE",
        "name": "五粮液",
        "asset_type": "stock",
        "currency": "CNY",
    },
    {
        "symbol": "300750.SZ",
        "exchange": "SZSE",
        "name": "宁德时代",
        "asset_type": "stock",
        "currency": "CNY",
    },
    {
        "symbol": "000333.SZ",
        "exchange": "SZSE",
        "name": "美的集团",
        "asset_type": "stock",
        "currency": "CNY",
    },
    {
        "symbol": "002594.SZ",
        "exchange": "SZSE",
        "name": "比亚迪",
        "asset_type": "stock",
        "currency": "CNY",
    },
    {
        "symbol": "000651.SZ",
        "exchange": "SZSE",
        "name": "格力电器",
        "asset_type": "stock",
        "currency": "CNY",
    },
    {
        "symbol": "002475.SZ",
        "exchange": "SZSE",
        "name": "立讯精密",
        "asset_type": "stock",
        "currency": "CNY",
    },
]


def seed_assets(db: Session) -> tuple[int, int]:
    """Upsert UNIVERSE into ``assets``; return ``(inserted, updated)``.

    Idempotent via ``ON CONFLICT (symbol, exchange) DO UPDATE``. On conflict
    the mutable metadata columns (name/asset_type/currency) are refreshed
    from the incoming row. ``xmax = 0`` distinguishes newly inserted rows
    from updated ones (an updated row's xmax holds the updating xact id).
    The caller receives a committed transaction; this function commits.
    """
    if not UNIVERSE:
        return (0, 0)

    rows = [
        {
            "symbol": r["symbol"],
            "exchange": r["exchange"],
            "name": r["name"],
            "asset_type": r["asset_type"],
            "currency": r["currency"],
        }
        for r in UNIVERSE
    ]
    stmt = pg_insert(Asset).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Asset.symbol, Asset.exchange],
        set_={
            "name": stmt.excluded.name,
            "asset_type": stmt.excluded.asset_type,
            "currency": stmt.excluded.currency,
        },
    ).returning(literal_column("(xmax = 0)").label("inserted"))
    result = db.execute(stmt)
    flags = [row.inserted for row in result]
    inserted = sum(1 for f in flags if f)
    updated = len(flags) - inserted
    db.commit()
    return (inserted, updated)


def main() -> None:
    """Run the seed against the configured database and print a summary."""
    db = SessionLocal()
    try:
        inserted, updated = seed_assets(db)
        print(f"Seeded {len(UNIVERSE)} assets: {inserted} inserted, {updated} updated")
    finally:
        db.close()


if __name__ == "__main__":
    main()
