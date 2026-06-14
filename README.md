# FinResearch Agent

> **FinResearch Agent: LLM-powered Financial Research and Backtesting System**
>
> An AI-ready financial research platform that integrates market data ingestion, time-series storage, data quality monitoring, quantitative backtesting, LLM-agent-based research planning, and automated research memo generation.

The project bridges AI engineering and financial technology by transforming natural-language investment hypotheses into reproducible research workflows with structured data retrieval, factor construction, risk evaluation, and benchmark comparison.

## Tech Stack

| Layer | Choice |
|---|---|
| Frontend | React + Vite + TypeScript + Ant Design + ECharts |
| Backend | FastAPI + SQLAlchemy 2.0 + Pydantic v2 |
| Database | PostgreSQL + TimescaleDB |
| Queue | Redis + RQ |
| Data Source | yfinance / OpenBB / Stooq |
| Quant | vectorbt / backtrader |
| Agent | LangGraph / tool-calling |
| DevOps | Docker Compose |
| Monorepo | pnpm workspace (frontend) + uv workspace (backend) |

## Repository Layout

```text
finresearch-agent/
  apps/
    web/                  # React frontend
    api/                  # FastAPI backend
    worker/               # Data sync & backtest worker
  packages/
    shared/               # Shared TS types, constants, schemas
  infra/
    docker/               # Docker config (postgres init, redis conf)
    migrations/           # Alembic migrations
  docs/                   # Architecture, schema, agent design
  notebooks/              # Factor & sentiment research notebooks
  tests/                  # Backend tests
  docker-compose.yml
  README.md
  .env.example
```

## Quick Start (Local, No Docker)

```bash
# 1. Install dependencies (mirrors configured for CN network)
pnpm install
make install-py         # = uv sync --all-packages

# 2. Configure environment
cp .env.example .env    # edit values for your local DB / Redis

# 3. Run backend (FastAPI on http://localhost:8000)
make api-dev

# 4. In another terminal, run frontend (Vite on http://localhost:5173)
make web-dev
```

Open http://localhost:5173 to see the dashboard. The backend API is at
http://localhost:8000 with interactive docs at http://localhost:8000/docs.

> The `/health` endpoint works without a database. Full features (auth,
> OHLCV sync, backtests) require PostgreSQL + TimescaleDB and Redis.
> See [Local Services](#local-services-postgresql--redis) below.

## Local Services (PostgreSQL + Redis)

The Week-1 dashboard and `/health` endpoint do not need a database. To use
any feature that hits the DB or queue, install locally:

```bash
# WSL2 / Debian / Ubuntu
sudo apt update
sudo apt install -y postgresql-15 redis-server

# Start services
sudo service postgresql start
sudo service redis-server start

# Create database + user (one-time)
sudo -u postgres createuser --createdb finresearch
sudo -u postgres psql -c "ALTER USER finresearch PASSWORD 'finresearch_dev_password';"
sudo -u postgres createdb -O finresearch finresearch

# Optional: install TimescaleDB (see https://docs.timescale.com/self-hosted/latest/install/)
```

Update `.env` to point at `localhost` instead of the docker service names:

```
DATABASE_URL=postgresql+psycopg://finresearch:finresearch_dev_password@localhost:5432/finresearch
REDIS_URL=redis://localhost:6379/0
```

Apply migrations:

```bash
# From repo root, with virtualenv active
uv run --package finresearch-api alembic -c infra/migrations/alembic.ini upgrade head
```

## Development

| Command | Description |
|---|---|
| `make install-py` | `uv sync --all-packages` — install Python deps for all workspace members |
| `make api-dev` | Run uvicorn with reload (no Docker) |
| `make web-dev` | Run vite dev server (no Docker) |
| `make worker-dev` | Run RQ worker (requires local Redis) |
| `make lint` | Run ruff + eslint |
| `make format` | Run ruff format + prettier |
| `make type-check` | Run TypeScript type checker |
| `make test` | Run pytest |

### Docker (optional)

If you prefer Docker, install Docker Desktop with WSL2 integration first,
then:

| Command | Description |
|---|---|
| `make up` | Start all Docker services |
| `make down` | Stop all Docker services |
| `make logs` | Tail Docker logs |
| `make psql` | Open psql inside postgres container |
| `make migrate` | Run `alembic upgrade head` inside api container |

## Roadmap

- **Week 1** — Data foundation & Dashboard skeleton
- **Week 2** — Backtesting engine & risk metrics
- **Week 3** — Factor research & parameter sensitivity
- **Week 4** — Financial text & sentiment factor
- **Week 5** — LLM Agent research workflow
- **Week 6** — Report generation & application materials

See [`docs/`](./docs/) for detailed design docs.

## License

Private project — for educational and application-portfolio use only.
