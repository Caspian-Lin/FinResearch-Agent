# Week 2 Progress — Backtesting Engine & Risk Metrics

Week 2 turns the Week 1 data foundation into a reproducible backtest workflow:
configure a strategy, trigger an async run, persist results, compare against a
benchmark, and inspect gross/net risk metrics. The system remains a research and
reproducibility tool, not an automated trading system.

## Delivered Scope

| Area | Status |
|---|---|
| Strategy engine | Vectorized daily engine with a single anti-look-ahead boundary: `holdings = decision.shift(1)` |
| Baseline strategies | Buy & Hold, Equal Weight, Moving Average Crossover, Momentum, Reversal |
| Risk metrics | Annual return, volatility, Sharpe, max drawdown, Calmar, turnover, win rate, beta, correlation |
| Cost comparison | Gross and net returns / metrics are stored separately |
| Benchmark comparison | Optional QQQ/SPY-style benchmark curve stored beside the strategy curve |
| Persistence | `backtest_runs`, `backtest_metrics`, `equity_curve`, `trades`; full parameter snapshot in `config_json` |
| Async execution | `POST /backtest` creates a pending run; RQ worker executes and persists results |
| Frontend | Configure -> trigger -> poll -> render metrics, equity, drawdown, benchmark, and trades |
| Anti-cheat audit | See `docs/backtesting-methodology.md` for FRA-39 coverage and limitations |

## Reproducible Demo

Prerequisites: local API, worker, web, Postgres, and Redis are running; migrations
and `make seed` have been applied; sample assets have been synced from yfinance
for the selected window.

Recommended sample:

| Field | Value |
|---|---|
| Data source | `yfinance` |
| Window | `2024-01-02` to `2024-03-29` |
| Universe | `NVDA`, `AMD` |
| Benchmark | `QQQ` |
| Strategies | Buy & Hold and Moving Average Crossover, or Buy & Hold and Momentum |
| Price field | `adjusted` |
| Rebalance | `daily` for Buy & Hold / MA; `monthly` is useful for Momentum sensitivity |
| Cost assumptions | Run at `0 bps` and at one non-zero cost such as `10 bps` |

Steps:

1. Open the web app and log in.
2. Add `NVDA`, `AMD`, and `QQQ` to a watchlist.
3. Sync yfinance daily bars for `2024-01-02` through `2024-03-29`.
4. Open Backtest, select the watchlist assets, choose `QQQ` as benchmark, and run Buy & Hold.
5. Run a second backtest with Moving Average Crossover or Momentum over the same window.
6. Confirm the result page shows gross/net metrics, strategy equity, benchmark equity, drawdown, and trades.
7. Open the run detail via API or DB and confirm `config_json` records the full snapshot: universe, window, strategy, params, rebalance, cost, price field, and benchmark.

## Acceptance Notes

- The frontend flow is configure -> trigger -> poll -> display; pending/running runs continue polling until success, failure, timeout, or unmount.
- Worker execution is asynchronous and writes metrics, strategy / benchmark curve points, and trade rows under one run id.
- Benchmark comparison is optional. A missing benchmark means beta/correlation may be absent or zero, not that the strategy is risk-free.
- The anti-cheat rules are implemented and tested in the engine, metrics, sensitivity, API snapshot, and train-forward validation tests.

## Limitations

- Universe membership is user-selected; the system does not yet have historical index constituents or delisted securities, so survivorship bias can remain.
- yfinance is a delayed public data source and may rate-limit or return incomplete data.
- The cost model is daily, close-to-close, linear `cost_bps`; it excludes slippage, market impact, taxes, partial fills, and intraday execution.
- Train -> forward validation is a Week 2 MVP demonstration, not a full factor research or significance-testing framework.
- Results are historical simulations bound to the selected data window, asset universe, and assumptions. They are not investment advice and do not imply profitability.

## Quality Gates

Before submitting Week 2 work:

```bash
make lint
make test
make type-check
```

If a local environment limitation prevents a gate from running, record the exact
reason in the issue or PR.
