# Week 3 Progress — Factor Research & Parameter Sensitivity

Week 3 adds a reproducible factor-research workflow on top of the Week 2
backtesting engine: compute factors from synced OHLCV, evaluate IC statistics,
run stratified quantile backtests, scan factor / parameter / cost sensitivity,
and render the results in the web UI. The system remains a research and
reproducibility tool, not a trading or investment-advice system.

## Delivered Scope

| Area | Status |
|---|---|
| Factor contracts | Backend protocols / dataclasses and shared TypeScript types for factor values, IC, and quantile results |
| Factor storage | `factor_values` hypertable keyed by `(asset_id, factor_name, time, source)` |
| Factor computation | Momentum `21/63/126`, reversal `5/21`, RSI `14`, MACD / MACD histogram, volatility `20d/63d` |
| Ranking / normalization | Cross-sectional rank, z-score, winsorization, and quantile buckets |
| IC evaluation | Spearman IC series, mean, ICIR, t-stat, p-value, positive rate, and sample count |
| Quantile backtest | Equal-weight buckets, top-minus-bottom spread, and monotonicity score |
| Sensitivity sweep | Factor x window x top-k / quantile x rebalance x cost grid with parameter-impact flags |
| API | `/factors/compute`, `/factors/values`, `/factors/{name}/ic`, `/factors/quantile-backtest`, `/factors/sensitivity`, plus async worker endpoints |
| Worker | RQ jobs for factor compute, quantile backtest, and sensitivity sweep with persisted `config_json` / `result_json` |
| Frontend | Factor Research page with IC chart, summary cards, quantile curves, and sensitivity heatmap |
| Methodology | `docs/factor-research-methodology.md` with anti-cheat audit, limitations, and implementation evidence |

## Reproducible Demo

Prerequisites: local API, worker, web, Postgres, and Redis are running; migrations
and `make seed` have been applied; user is logged in. The sample below uses
yfinance daily bars, explicit dates, adjusted prices, and a small three-asset
universe.

Recommended sample:

| Field | Value |
|---|---|
| Data source | `yfinance` |
| Window | `2024-01-02` to `2024-12-31` |
| Universe | `NVDA`, `AMD`, `QQQ` |
| Factors | `momentum_63`, `rsi_14` |
| IC horizon | `5` trading days |
| Quantile layers | `5` |
| Sensitivity costs | `0`, `5`, `10`, `25` bps |
| Price field | `adjusted` |

Steps:

1. Open the web app and log in.
2. Create or open a watchlist containing `NVDA`, `AMD`, and `QQQ`.
3. Sync yfinance daily bars for `2024-01-02` through `2024-12-31` for all three assets.
4. Open Factor Research, select the watchlist, choose `momentum_63`, the same date window, `5` quantiles, and adjusted prices.
5. Run the IC view and confirm the chart plus summary cards render mean IC, ICIR, t-stat, p-value, positive rate, and sample count.
6. Run the quantile view and confirm quantile equity curves, top-minus-bottom spread, and monotonicity render after the worker job reaches `success`.
7. Run the sensitivity view and confirm the heatmap renders net Sharpe by window and cost after the worker job reaches `success`.
8. Repeat the IC view with `rsi_14` over the same universe and window.
9. Optionally confirm the API / DB snapshots: factor values are in `factor_values`, async runs are in `backtest_runs`, and every run records the full universe, window, source, factor, horizon / quantile / sweep grid, price field, and cost assumptions.

The same flow can be exercised through Swagger at `http://localhost:8000/docs`
using `/factors/compute`, `/factors/{name}/ic`, `/factors/quantile-backtest`,
and `/factors/sensitivity` after authenticating. Asset UUIDs come from
`GET /assets`.

## Acceptance Notes

- The Week 3 flow is configure -> trigger -> poll -> display for async quantile
  and sensitivity jobs; IC can run synchronously from the same configuration.
- Factor computation reuses the Week 2 price reader and stores non-NaN values
  idempotently in `factor_values`.
- IC forward returns are evaluation-only. They never enter factor computation
  or decision-time holdings.
- Quantile backtests reuse the Week 2 engine, so the anti-look-ahead boundary is
  still `holdings = decision.shift(1)`.
- Sensitivity points share the same price matrix for comparability, and cost is
  an explicit grid dimension.
- Every API response or async run carries a reproducibility snapshot. Results are
  bound to the selected data window, universe, source, factor, and assumptions.

## Week 3 Deliverables vs Project §14

| Project §14 deliverable | Implementation |
|---|---|
| 1M / 3M / 6M momentum | `momentum_21`, `momentum_63`, `momentum_126` in `app/services/factors/momentum.py` |
| RSI, MACD, volatility | `rsi_14`, `macd`, `macd_hist`, `volatility_20d`, `volatility_63d`; default API demo uses the registered persisted factors `rsi_14` and `volatility_*` |
| Factor ranking | `app/services/factors/ranking.py` rank / z-score / winsorize / quantile bucket |
| Parameter sensitivity experiment | `factor_sensitivity_configs`, `run_sweep`, `summarize_sweep` |
| Transaction-cost impact | Cost bands `0/5/10/25` bps in factor sensitivity; gross vs net metrics retained |
| Factor performance report | Factor Research page: IC chart, IC summary cards, quantile curves, top-minus-bottom, heatmap |

## Quality Gates

Before submitting Week 3 work:

```bash
make lint
make test
make type-check
```

If a local environment limitation prevents a gate from running, record the exact
reason in the issue or PR.

## Limitations

- The default demo universe is tiny and user-selected. It is useful for
  reproducibility, not for broad statistical inference.
- The system does not have historical index constituents or delisted securities;
  survivorship bias can remain.
- yfinance is a single delayed public source and may rate-limit or return
  incomplete adjusted data.
- IC significance over short windows is unstable, and parameter grids are
  in-sample unless paired with a separate forward window.
- The cost model is a simple daily proportional `cost_bps` model. It excludes
  slippage, market impact, borrow, taxes, partial fills, and intraday execution.
- Factor results are historical simulations bound to the selected data window,
  asset universe, and assumptions. They are not investment advice and do not
  imply profitability.

## Next Week

Week 4 — financial text and sentiment factor:

- News headline / summary collection
- Sentiment prompt or model
- `sentiment_score` persistence
- Sentiment plus technical-factor comparison
- Text-factor limitations and source-quality notes
