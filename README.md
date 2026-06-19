# FinResearch Agent

> **FinResearch Agent — LLM-powered Financial Research and Backtesting System**

FinResearch Agent turns natural-language investment hypotheses into reproducible
research workflows: structured market-data retrieval → factor construction →
backtesting → risk evaluation → benchmark comparison → automated research memo.

It is a **research automation and reproducibility tool**. It is **not** an
automated trading bot, it does not connect to any brokerage, and it does not
promise profit. Nothing here is investment advice — see
[Disclaimer](#disclaimer).

The UI ships in **English** and **简体中文**; switch at any time from the header.

---

## Table of Contents

- [Project Motivation](#project-motivation)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Data Schema](#data-schema)
- [Internationalization](#internationalization)
- [How to Run](#how-to-run)
- [1-Minute Demo](#1-minute-demo)
- [Data Sources, Adjusted Prices & Quality Checks](#data-sources-adjusted-prices--quality-checks)
- [Disclaimer](#disclaimer)
- [Week 1 Progress](#week-1-progress)
- [Week 2 Progress](#week-2-progress)
- [Roadmap / Next Steps](#roadmap--next-steps)

---

## Project Motivation

Bridging AI engineering and financial technology means more than calling an LLM
on a stock ticker. A trustworthy research pipeline must be **reproducible**:
every conclusion bound to a stated data window, asset universe, and set of
assumptions, with quality and risk surfaced rather than hidden.

Week 1 builds the **data foundation**: a system you can sign in to, manage a
watchlist by stable asset identity, sync daily OHLCV on demand, and inspect both
the price series and its data health — all in two languages. The later weeks add
backtesting, factor research, NLP sentiment, and an LLM agent that plans a
research task end-to-end.

The emphasis throughout is on **methodology and risk**, not on performance. If a
backtest ever looks too good, suspect a bug first.

## Tech Stack

| Layer | Choice |
|---|---|
| Frontend | React 18 + Vite + TypeScript + Ant Design 5 + ECharts 5 + i18next |
| Backend | FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Pydantic Settings |
| Database | PostgreSQL 16 + TimescaleDB (OHLCV hypertable) |
| Queue | Redis 7 + RQ |
| Data Source | yfinance (Week 1); OpenBB / Stooq + domestic sources planned |
| Quant | vectorbt / backtrader (planned) |
| Agent | OpenAI-compatible API + tool-calling workflow (LangGraph optional) |
| DevOps | Docker Compose (optional; local-first for dev) |
| Monorepo | pnpm workspace (frontend) + uv workspace (backend) |

## Architecture

```text
React / Vite Dashboard  ──HTTP──▶  FastAPI Backend
                                      │
                    ┌─────────────────┼──────────────────┐
                    ▼                 ▼                  ▼
              PostgreSQL +      Redis Queue ──▶  RQ Worker
             TimescaleDB        (sync jobs)     (yfinance ingest)
```

| Service | Responsibility |
|---|---|
| **web** (`apps/web`) | Login/register, watchlist, dashboard: price charts (line/candle/area + volume + MA), sync control, data-quality panel |
| **api** (`apps/api`) | Auth (JWT), asset/watchlist CRUD, OHLCV query, on-demand sync trigger + status, quality report |
| **worker** (`apps/worker`) | RQ job: fetch OHLCV from yfinance, idempotent upsert into the hypertable |
| **postgres** | Relational metadata (`users`, `assets`, `watchlist`, `watchlist_items`) + `ohlcv` TimescaleDB hypertable |
| **redis** | RQ job queue + status |

### API surface (Week 1)

The interactive contract lives at **http://localhost:8000/docs** (Swagger) and
`/redoc`. Endpoint groups:

| Group | Purpose |
|---|---|
| `GET /health` | Liveness probe (works without a DB) |
| `/auth` | `POST /register`, `POST /login` (JWT), `GET /me` |
| `/assets` | Create / list / get assets by `asset_id` |
| `/watchlists` | CRUD watchlists + add/remove items (ownership-enforced) |
| `/ohlcv` | Query bars by `asset_id` + `source` + time window |
| `/sync` | `POST` trigger a sync job, `GET /sync/{job_id}` poll status |
| `/quality/{asset_id}` | Missing-bar + anomaly stats for a window |

## Data Schema

All business tables use **`asset_id UUID`** primary keys (server-side
`gen_random_uuid()`), decoupling identity from the mutable `symbol` so corporate
actions (splits, renames, symbol reuse) don't break references. This is why the
Week 1 schema moved from `symbol PK` to `asset_id UUID` (FRA-13).

| Table | Key | Notes |
|---|---|---|
| `users` | `id UUID` | `email` unique; password hashed |
| `assets` | `id UUID` | metadata; `UNIQUE(symbol, exchange)` |
| `watchlist` | `id UUID` | per-user list; `UNIQUE(user_id, name)` |
| `watchlist_items` | `(watchlist_id, asset_id)` | many-to-many asset ↔ watchlist |
| `ohlcv` | `(asset_id, time, source)` | daily bars; TimescaleDB hypertable on `time` |

`ohlcv` columns: `open, high, low, close, adjusted_close, volume` — `close` is
the **raw** close, `adjusted_close` is the **split/dividend-adjusted** close.

Full DDL and indexing rationale: [`docs/database-schema.md`](./docs/database-schema.md).

## Internationalization

The frontend supports **English (`en`)** and **简体中文 (`zh-CN`)**.

- **Default language rule** (first match wins):
  1. Saved preference in `localStorage` (`fra.lang`)
  2. Browser language — any `zh*` locale maps to `zh-CN`
  3. Fallback: `en`
- **Switching**: a language dropdown in the app header toggles between
  **English** and **简体中文** instantly — **no page reload** — and the choice is
  persisted for next time.
- Translation keys are organized by domain (`common`, `auth`, `watchlist`,
  `dashboard`, `errors`); page code carries no hardcoded UI strings.

## How to Run

Two modes: **Local (no Docker)** — the default for development — and **Docker
Compose**. All commands below run from the repo root via the `Makefile`.

> The `/health` endpoint and the bare dashboard shell work without a database.
> Auth, watchlist, OHLCV sync, and quality require **PostgreSQL + TimescaleDB**
> and **Redis**.

### Prerequisites

- Python 3.11 (managed by [uv](https://docs.astral.sh/uv/))
- Node 20+ with [pnpm](https://pnpm.io/)
- PostgreSQL 16 with the **TimescaleDB** extension (the `ohlcv` hypertable needs it)
- Redis 7

### Mode A — Local (no Docker, recommended for dev)

```bash
# 1. Install dependencies (CN mirrors are configured)
make install            # = pnpm install + uv sync --all-packages

# 2. Configure environment
cp .env.example .env    # defaults already target localhost; edit secrets

# 3. (WSL2/Debian/Ubuntu) start local services + create DB/user (one-time)
sudo apt update && sudo apt install -y postgresql-15 redis-server
sudo service postgresql start && sudo service redis-server start
sudo -u postgres createuser --createdb finresearch
sudo -u postgres psql -c "ALTER USER finresearch PASSWORD 'finresearch_dev_password';"
sudo -u postgres createdb -O finresearch finresearch
# Install the TimescaleDB extension into that cluster
#   (https://docs.timescale.com/self-hosted/latest/install/)

# 4. Apply migrations + seed the sample universe (~50 US + A-share instruments)
uv run --package finresearch-api alembic -c infra/migrations/alembic.ini upgrade head
make seed

# 5. Run the stack — pick one:
make dev                # api (:8000) + worker + web (:5173) in one terminal (Ctrl+C stops all)
# — or, in three terminals —
make api-dev            # FastAPI on http://localhost:8000 (reload)
make worker-dev         # RQ worker (needs local Redis)
make web-dev            # Vite on http://localhost:5173
```

Open **http://localhost:5173**. Backend interactive docs:
**http://localhost:8000/docs**.

`make seed` populates **asset metadata only** (NVDA, AMD, AAPL, QQQ, … plus
A-share blue chips). **Price history is synced on demand per asset** from the
dashboard — the seed script never fetches OHLCV.

### Mode B — Docker Compose

Docker brings up postgres (TimescaleDB image), redis, api, worker, and web
together. In `.env`, point the hosts at the Compose **service names** instead of
`localhost`:

```ini
DATABASE_URL=postgresql+psycopg://finresearch:finresearch_dev_password@postgres:5432/finresearch
REDIS_URL=redis://redis:6379/0
```

Then:

```bash
make up                 # docker compose up -d  (start everything)
make migrate            # alembic upgrade head, inside the api container
# seed runs on the host against the exposed port:
make seed               # uv run --package finresearch-api python -m app.db.seed
make logs               # docker compose logs -f
make down               # docker compose down
```

### Development commands

| Command | Description |
|---|---|
| `make install` | Install Python + Node deps |
| `make api-dev` / `make web-dev` / `make worker-dev` | Run one service locally |
| `make dev` | Run api + worker + web together |
| `make migrate` | Apply Alembic migrations (Docker) |
| `make seed` | Seed the sample asset universe |
| `make lint` | ruff + eslint |
| `make format` | ruff format + prettier |
| `make type-check` | TypeScript type checker |
| `make test` | pytest |
| `make up` / `make down` / `make logs` / `make psql` | Docker orchestration |

## 1-Minute Demo

A reproducible walk-through (no screenshots required). Prerequisites: stack
running, migrations + `make seed` applied.

1. **Open** http://localhost:5173 — you land on the login page.
2. **Switch language** from the header dropdown (English ↔ 简体中文); the whole
   UI updates instantly.
3. **Register** a new account, then **log in** (or use the seeded admin from
   `.env`). You're redirected to the dashboard/watchlist.
4. **Open Watchlist**, create a list, and **add assets** (e.g. `NVDA`, `AMD`,
   `QQQ`) — selected by stable `asset_id`.
5. **Open the Dashboard**, pick an asset from the watchlist.
6. Click **Sync Data** — watch the status move from *running* → *success* (the
   worker fetches daily OHLCV from yfinance and upserts it).
7. The **price chart** renders (switch Line / Candle / Area, toggle volume and
   MA5/MA20, flip Adjusted ↔ Raw).
8. The **Data Quality** panel shows missing-bar and anomaly statistics for the
   synced window.

> Sync depends on **yfinance**. Under rate-limiting you may see an empty result
> or a `running → failed` transition — see
> [Known Limitations](#data-sources-adjusted-prices--quality-checks) and
> `docs/week1-progress.md`.

### Week 2 Backtest Demo

After syncing sample assets such as `NVDA`, `AMD`, and `QQQ`, open the Backtest
page and run two strategies over the same explicit window, for example
`2024-01-02` to `2024-03-29`: Buy & Hold plus Moving Average Crossover or
Momentum, with `QQQ` as benchmark. The result page shows strategy vs benchmark
equity, drawdown, trades, and gross/net risk metrics. Each run persists its
full parameter snapshot in `config_json`, including universe, date window,
strategy params, rebalance, cost, price field, and benchmark.

See [`docs/week2-progress.md`](./docs/week2-progress.md) and
[`docs/backtesting-methodology.md`](./docs/backtesting-methodology.md) for the
anti-cheat audit, train→forward validation boundary, cost assumptions, and known
limitations.

## Data Sources, Adjusted Prices & Quality Checks

Be explicit about what the data is and isn't:

- **Source.** Week 1 ingests from **yfinance** only (delayed daily bars). Each
  `ohlcv` row carries a `source` column (`'yfinance'`) so the same asset can
  later hold bars from multiple providers. Domestic sources (AkShare/Tushare)
  and OpenBB/Stooq are planned (FRA-23).
- **Time window.** Sync takes an explicit `[start, end]` (ISO dates, inclusive).
  There is no automatic history backfill — you sync what you want to see.
- **Adjusted vs raw.** yfinance is queried with `auto_adjust=False`, so both
  values are stored: `close` = raw Close, `adjusted_close` = `Adj Close` (a
  split- and dividend-adjusted, back-adjusted price). The dashboard lets you
  view either. Timestamps are normalized to **UTC midnight** of the trading day
  so rows align across sources and timezones.
- **Quality checks.** Missing bars are computed against each exchange's trading
  calendar (weekends/holidays are **not** counted as gaps). Anomaly rules cover
  OHLC consistency (e.g. high ≥ low), zero/negative prices, and abnormal
  returns. **Week 1 computes these on demand and does not persist
  `data_quality_reports`** — coverage/anomaly figures are a data-health
  reference, indicative rather than exhaustive.

**Known limitations (honest):**

- **yfinance rate-limiting.** The public yfinance endpoint enforces IP-level
  throttling; a sync can return 0 bars and (per FRA-22) the job may currently
  report success on an empty fetch. If a chart is empty, suspect the source
  before the code.
- **A-share data.** yfinance coverage and field completeness for China A-shares
  is uneven; treat A-share series with extra caution until domestic adapters
  land (FRA-23).
- **Single source.** No cross-source reconciliation yet; a bar from yfinance is
  the only version of truth for now.

This is a **research/reproducibility** tool. It does not claim to beat the
market, generate profit, or provide investment advice.

## Disclaimer

> **English** — FinResearch Agent is a research and reproducibility tool. It is
> **not** an automated trading bot, does not connect to brokerages, and does not
> guarantee profit. Any output is bound to a stated data window, asset universe,
> and assumptions. This is not investment advice.

> **简体中文** — FinResearch Agent 是研究与可复现性工具。它**不是**自动化交易
> 机器人，不接入券商，也不承诺盈利。任何输出均绑定于明确的数据窗口、资产范围
> 与假设条件。本工具的内容**不构成投资建议**。

## Week 1 Progress

Week 1 — **Data Foundation & Dashboard** — is complete: schema + migrations,
JWT auth, asset/watchlist APIs and pages, on-demand OHLCV sync (yfinance + RQ),
data-quality checks, an i18n dashboard with line/candle/area charts, and the
sample asset seed.

Known follow-ups carried into later weeks: the sync-on-empty false-success issue
(FRA-22) and domestic data-source adapters (FRA-23).

Details — deliverables, blockers, known limitations, next week:
[`docs/week1-progress.md`](./docs/week1-progress.md).

## Week 2 Progress

Week 2 — **Backtesting Engine & Risk Metrics** — is implemented as an async,
reproducible research workflow: baseline strategies, gross/net metrics,
benchmark comparison, result persistence, trade details, and a frontend
configure→trigger→poll→display flow.

The anti-cheat audit is documented in
[`docs/backtesting-methodology.md`](./docs/backtesting-methodology.md), including
look-ahead protection, survivorship-bias limitations, train→forward validation,
cost model assumptions, and reproducibility requirements. Demo steps and
acceptance notes live in [`docs/week2-progress.md`](./docs/week2-progress.md).

## Roadmap / Next Steps

- **Week 1** ✅ Data foundation & dashboard skeleton
- **Week 2** ✅ Backtesting engine & risk metrics (Buy&Hold, equal-weight, MA,
  momentum; Sharpe / max drawdown / volatility / turnover vs benchmark)
- **Week 3** — Factor research & parameter sensitivity
- **Week 4** — Financial text & sentiment factor
- **Week 5** — LLM agent research workflow
- **Week 6** — Report generation & application materials

Design docs in [`docs/`](./docs/): `architecture.md`, `database-schema.md`,
`agent-design.md`, `backtesting-methodology.md`, `week1-progress.md`,
`week2-progress.md`.

## License

Private project — for educational and application-portfolio use only.
