# @finresearch/api — FastAPI Backend

The API service exposes REST endpoints for:

- User authentication (JWT)
- Asset & watchlist management
- Market data sync triggers
- Data quality reports
- Backtest runs & results
- Research memos
- LLM Agent orchestration

## Layout

```text
apps/api/
  app/
    main.py            # FastAPI app entry, mounts routers
    core/
      config.py        # Pydantic Settings
      logging.py       # Structured JSON logging
    db/
      session.py       # SQLAlchemy engine + session factory
      base.py          # Declarative Base
    api/
      v1/
        health.py      # GET /health
        auth.py        # /auth/login, /auth/register
        assets.py      # /assets CRUD
        watchlists.py  # /watchlists CRUD
        ohlcv.py       # /ohlcv sync + query
        quality.py     # /quality reports
        backtests.py   # /backtests run + results
        memos.py       # /memos list + detail
    models/            # SQLAlchemy ORM models
    schemas/           # Pydantic request/response schemas
    services/          # Business logic
    agents/            # LLM agent tools
  tests/               # Module-level unit tests
  pyproject.toml
  Dockerfile
```

## Local Development

```bash
# From repo root
make api-dev                # uvicorn with reload
# Or via Docker
make up SERVICE=api
make logs SERVICE=api
```

## Endpoints (planned)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe |
| POST | `/auth/register` | Register new user |
| POST | `/auth/login` | Issue JWT |
| GET | `/assets` | List assets |
| POST | `/assets` | Add asset |
| GET | `/watchlists` | List user watchlists |
| POST | `/watchlists/{id}/assets` | Add asset to watchlist |
| POST | `/ohlcv/sync` | Trigger sync job |
| GET | `/ohlcv` | Query historical OHLCV |
| GET | `/quality/{asset_id}` | Get data quality report |
| POST | `/backtests` | Run a backtest |
| GET | `/backtests/{id}` | Get backtest result |
| GET | `/memos` | List research memos |
