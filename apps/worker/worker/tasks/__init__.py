"""Worker tasks.

Each module exposes top-level functions (RQ imports them by dotted path).
Add modules here as they are implemented:

- ``sync_ohlcv``  — Week 1: OHLCV ingestion via yfinance
- ``quality``     — Week 1: data quality checks
- ``backtest``    — Week 2: strategy backtests
- ``factors``     — Week 3: factor computation
- ``sentiment``   — Week 4: news sentiment scoring
- ``report``      — Week 5-6: research memo generation
"""
