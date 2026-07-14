# Week 4 Progress — Financial Text & Sentiment Factor

Week 4 adds a financial-text pipeline on top of the Week 1–3 data and backtesting
infrastructure: news headline/summary ingestion, sentiment classification (rule +
LLM), daily sentiment factor with anti-look-ahead timestamp alignment, a
technical-only vs technical+sentiment comparison backtest, and a Sentiment Research
UI with news / scores / factor / comparison tabs. The system remains a research and
reproducibility tool — it is not a trading system and does not produce investment
advice.

## Delivered Scope

| Area | Status |
|---|---|
| Interface contracts | Shared types and in-memory dataclasses for news items, sentiment scores, factor frames, summaries, and comparison results (`packages/shared`, `app.services.sentiment.types`) |
| Database migration | `news_items` table (headline dedup via `headline_hash`, raw payload preserved) and `sentiment_scores` table (`model_name` + `prompt_version` + `params` + `raw_response` for reproducibility) |
| News ingestion | Provider-based news sync with idempotent upsert; sync and async-async (RQ worker) variants |
| Sentiment classification | Fixture rule classifier (deterministic keyword) + LLM classifier (OpenAI-compatible); idempotent upsert by `(news_item_id, model_name)` |
| Sentiment factor | `compute_sentiment_factor()` maps `published_at → signal_date` (first trading day ≥ pub, never earlier); daily mean aggregation; NaN = no coverage (no forward-fill); persists to `factor_values` with `news_count` companion |
| Sentiment summaries | Rolling `window_days` lookback aggregates with label counts and overnight capture |
| Comparison backtest | `SentimentTechStrategy` with `overlay` / `combined` fusion modes; pure-function `run_comparison()` + state-machine `execute_comparison_run()` creating parent–child `BacktestRun` rows |
| Sentiment API | `POST /sentiment/news/sync` (+async), `GET /sentiment/news`, `POST /sentiment/score` (+async), `GET /sentiment/scores`, `GET /sentiment/factor`, `POST /sentiment/factor/compute` (+async), `GET /sentiment/summaries`, `GET /sentiment/jobs/{run_id}`; `POST /backtest/comparison`, `GET /backtest/comparison/{run_id}` |
| Worker | RQ jobs for news sync, sentiment classification, and factor computation with persisted `config_json` / `result_json` |
| Frontend | Sentiment Research page with four tabs: News (ingest + list), Scores (classify + list), Factor (compute + chart), Comparison (configure + run + equity/metrics) |
| Methodology | `docs/sentiment-factor-methodology.md` with 11-row anti-cheat audit table (implementation + test evidence), 8-section limitations, and non-goals |

## Reproducible Demo

Prerequisites: local API, worker, web, Postgres, and Redis are running; migrations
and `make seed` have been applied; sample assets (`NVDA`, `AMD`, `QQQ`) have been
synced from yfinance for the selected window. The demo uses the fixture classifier
(no LLM API key required).

Recommended sample:

| Field | Value |
|---|---|
| Data source | `yfinance` (OHLCV) + `fixture` provider (news) |
| OHLCV window | `2024-01-02` to `2024-06-30` |
| News window | `2024-01-02` to `2024-06-30` |
| Universe | `NVDA`, `AMD`, `QQQ` |
| Classifier | `fixture` (keyword rule; deterministic, no API key) |
| Factor model | `fixture-rule` |
| Comparison mode | `overlay` |
| Cost | `10` bps |
| Rebalance | `monthly` |

Steps:

1. Open the web app and log in.
2. Create or open a watchlist containing `NVDA`, `AMD`, and `QQQ`.
3. Sync yfinance daily bars for `2024-01-02` through `2024-06-30` (Dashboard →
   Sync).
4. Open **Sentiment Research** → **News** tab. Select the watchlist, set the date
   window, and click **Sync News**. Confirm news items appear in the list with
   source, published timestamp, and headline.
5. Switch to the **Scores** tab. Click **Classify** (fixture classifier). Confirm
   sentiment scores appear with `label`, `score` (−1..+1), `confidence`, and
   `model_name`.
6. Switch to the **Factor** tab. Select the watchlist, the same window, and
   `model_name = fixture-rule`. Click **Compute Factor**. Confirm the ECharts
   sentiment-factor line chart renders per asset (NaN days are gaps, not zeros).
7. Switch to the **Comparison** tab. Configure:
   - Universe: same watchlist
   - Window: same dates
   - Technical factor: `momentum_21`
   - Top-k: `2`
   - Mode: `overlay`
   - Sentiment threshold: `0.0`
   - Cost: `10` bps
   - Rebalance: `monthly`
8. Click **Run Comparison**. The frontend polls until the job reaches `success`,
   then renders equity curves and metrics for `technical_only` vs
   `technical_sentiment` side-by-side.
9. Open the run detail via Swagger (`GET /backtest/comparison/{run_id}`) and
   confirm the parent run records `run_kind = sentiment_comparison` with child run
   IDs; each child run's `config_json` captures the full strategy, cost, and
   sentiment parameters.

The same flow can be exercised through Swagger at `http://localhost:8000/docs`
using `POST /sentiment/news/sync`, `POST /sentiment/score`, `POST
/sentiment/factor/compute`, and `POST /backtest/comparison` after authenticating.
Asset UUIDs come from `GET /assets`.

## Acceptance Notes

- The Sentiment Research flow is **ingest → classify → build factor → compare**,
  each step idempotent (re-running over the same window upserts, not duplicates).
- News `published_at` is the anti-look-ahead anchor: it maps to the first trading
  day ≥ it (`signal_date`), never earlier. Intraday / after-hours news maps to the
  next trading day.
- NaN sentiment (no news coverage) is preserved as NaN — no forward-fill, no
  zero-fill. In `overlay` mode, NaN-sentiment assets are filtered out (not held);
  in `combined` mode they are skipped in the weighted rank.
- The comparison backtest reuses the Week 2 engine, so the execution boundary
  remains `holdings = decision.shift(1)`. `SentimentTechStrategy` only outputs
  decision-day target weights; the engine applies the one-day lag.
- Every API response carries a `config_snapshot` (universe, window, model_name,
  classifier, provider) so results are bound to a stated data window, asset
  universe, source, classifier/model version, and assumptions.
- The fixture classifier makes the demo fully reproducible without external API
  keys or network dependencies beyond yfinance.

## Week 4 Deliverables vs Project §14

| Project §14 deliverable | Implementation |
|---|---|
| 新闻标题/摘要采集 | `app/services/sentiment/provider.py` + `app/services/sentiment/service.py::sync_news()`; provider fixture returns deterministic headlines for demo; `POST /sentiment/news/sync` (+async worker job) |
| 情绪分类 prompt 或模型 | `app/services/sentiment/classifier.py` — `FixtureClassifier` (keyword rule) + `LLMClassifier` (OpenAI-compatible JSON); `prompt_version` persisted per score |
| sentiment score 入库 | `sentiment_scores` table with `(news_item_id, model_name)` conflict key; `label` / `score` / `confidence` / `raw_response` / `params`; `compute_and_store_sentiment_factor()` persists daily factor to `factor_values` |
| sentiment + technical 策略对比 | `SentimentTechStrategy` (overlay / combined); `run_comparison()` + `execute_comparison_run()`; `POST /backtest/comparison` + `GET /backtest/comparison/{run_id}` |
| 文本因子局限性说明 | `docs/sentiment-factor-methodology.md` — 11-row anti-cheat audit table, 8-section limitations (LLM drift, news coverage bias, overfitting, survivorship, etc.), non-goals |

## Quality Gates

Before submitting Week 4 work:

```bash
make lint
make test
make type-check
```

Backend: ruff + mypy strict + pytest (including
`test_sentiment_factor.py`, `test_sentiment_classify.py`,
`test_sentiment_comparison.py`, `test_sentiment_contracts.py`,
`test_sentiment_api.py`). Frontend: tsc --noEmit + eslint + vitest (including
`api/__tests__/sentiment.test.ts`).

## Limitations

- **News coverage bias.** The fixture provider returns deterministic sample
  headlines for demo purposes; a real provider (yfinance news, OpenBB, etc.) may
  not cover all assets or all dates. Missing coverage = NaN, not neutral. See
  `docs/sentiment-factor-methodology.md §Limitations`.
- **LLM classification non-determinism.** LLM scores may change across model
  versions or sampling runs. `model_name` + `prompt_version` are persisted for
  auditability, but exact reproducibility is not guaranteed. `raw_response` is
  stored per score when available.
- **Short-window overfitting.** The demo universe is tiny (3 assets) and the
  window is short (~6 months). Tuning `sentiment_threshold` / `sentiment_weight`
  on this sample almost certainly overfits. Results require independent forward
  validation before any extrapolation.
- **Same survivorship / single-source / simple-cost caveats** as Week 2 and
  Week 3 apply.
- All sentiment factor and comparison results are **historical simulations** bound
  to the selected data window, asset universe, source, classifier/model version,
  and assumptions. They are not investment advice and do not imply profitability.

## Next Week

Week 5 — LLM Agent research workflow:

- Research Planner Agent (NL → structured plan)
- Data / Factor / Backtest / Risk / Report agents
- Tool-calling execution loop with audit log
- JSON plan schema and citation of data windows / assumptions
