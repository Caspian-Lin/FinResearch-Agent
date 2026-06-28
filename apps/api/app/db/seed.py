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

# Sample universe (~50 instruments), FRA-78 unified symbol convention.
# Every symbol carries an exchange suffix so it round-trips unambiguously
# across data sources:
# - US large-caps: NASDAQ ``.O`` / NYSE ``.N``, USD
# - US ETFs: AMEX ``.A``, USD
# - A-share blue chips: SSE ``.SH`` / SZSE ``.SZ``, CNY (legacy ``.SS`` is no
#   longer used — FRA-78 standardized SSE to ``.SH``); name is the Chinese
#   company name.
# ``data_source`` records each asset's preferred source and is upserted
# alongside the metadata so re-seeds can refresh it: A-shares → ``akshare``,
# everything else (US/HK) → ``yfinance``.
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
        "data_source": "akshare",
    },
    {
        "symbol": "601318.SH",
        "exchange": "SSE",
        "name": "中国平安",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
    {
        "symbol": "600036.SH",
        "exchange": "SSE",
        "name": "招商银行",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
    {
        "symbol": "601398.SH",
        "exchange": "SSE",
        "name": "工商银行",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
    {
        "symbol": "600276.SH",
        "exchange": "SSE",
        "name": "恒瑞医药",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
    {
        "symbol": "601012.SH",
        "exchange": "SSE",
        "name": "隆基绿能",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
    {
        "symbol": "000001.SZ",
        "exchange": "SZSE",
        "name": "平安银行",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
    {
        "symbol": "000858.SZ",
        "exchange": "SZSE",
        "name": "五粮液",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
    {
        "symbol": "300750.SZ",
        "exchange": "SZSE",
        "name": "宁德时代",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
    {
        "symbol": "000333.SZ",
        "exchange": "SZSE",
        "name": "美的集团",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
    {
        "symbol": "002594.SZ",
        "exchange": "SZSE",
        "name": "比亚迪",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
    {
        "symbol": "000651.SZ",
        "exchange": "SZSE",
        "name": "格力电器",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
    {
        "symbol": "002475.SZ",
        "exchange": "SZSE",
        "name": "立讯精密",
        "asset_type": "stock",
        "currency": "CNY",
        "data_source": "akshare",
    },
]


def seed_assets(db: Session) -> tuple[int, int]:
    """Upsert UNIVERSE into ``assets``; return ``(inserted, updated)``.

    Idempotent via ``ON CONFLICT (symbol, exchange) DO UPDATE``. On conflict
    the mutable metadata columns (name/asset_type/currency/data_source) are
    refreshed from the incoming row. ``list_status`` is not seeded — it keeps
    the model default ``active`` and is only mutated by listing-state syncs.
    ``xmax = 0`` distinguishes newly inserted rows from updated ones (an
    updated row's xmax holds the updating xact id). The caller receives a
    committed transaction; this function commits.
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
            "data_source": r["data_source"],
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
            "data_source": stmt.excluded.data_source,
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
