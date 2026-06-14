# AGENTS.md

> Guide for AI coding agents (Claude Code, Codex, Cursor, etc.) working in this repo.
> Read this before making changes.

## Project

This repository contains **FinResearch Agent** — an AI-ready financial research and
backtesting platform. It turns natural-language investment hypotheses into reproducible
research workflows: structured data retrieval → factor construction → backtesting →
risk evaluation → benchmark comparison → automated research memo.

**Positioning**: a research automation & reproducibility tool. It is **NOT** an
automated trading bot, does not connect to brokerages, and does not promise profit.

## Stack

| Layer | Choice |
|---|---|
| Frontend | React 18 + Vite 5 + TypeScript 5 + Ant Design 5 + ECharts 5 |
| Backend | FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Pydantic Settings |
| Database | PostgreSQL 16 + TimescaleDB (hypertables for OHLCV time series) |
| Queue | Redis 8 + RQ |
| Data source | yfinance (default), OpenBB / Stooq (planned) |
| Quant | vectorbt / backtrader (planned) |
| LLM / Agent | OpenAI-compatible API + custom tool-calling workflow (LangGraph optional) |
| Monorepo | pnpm workspace (frontend) + uv workspace (backend) |
| Runtime | Python 3.11, Node 20+ |
| DevOps | Docker Compose (optional; local-first for dev) |

## Repository Layout

```text
apps/
  api/         FastAPI backend (app/main.py, core/, db/, api/, models/, schemas/, services/)
  worker/      RQ worker (data sync, backtest, report jobs)
  web/         Vite + React dashboard (src/)
packages/
  shared/      @finresearch/shared — TS types, zod schemas, constants (frontend/backend shared)
infra/
  docker/      postgres init.sql, redis.conf
  migrations/  Alembic (alembic.ini, env.py, versions/)
docs/          architecture, database-schema, agent-design, backtesting-methodology, week1-progress
notebooks/     factor_research.ipynb, sentiment_experiment.ipynb
tests/         pytest (test_*.py, conftest.py)
```

## Common Commands

All commands run from repo root via `Makefile`.

```bash
# Install
make install              # pnpm install + uv sync --all-packages
make install-py           # uv sync --all-packages (backend deps for all workspace members)
make install-node         # pnpm install

# Local dev (no Docker needed)
make api-dev              # FastAPI on http://localhost:8000 (reload)
make web-dev              # Vite on http://localhost:5173
make worker-dev           # RQ worker (requires local Redis)

# Quality gates (run before submitting)
make lint                 # ruff + eslint
make format               # ruff format + prettier
make type-check           # tsc --noEmit
make test                 # pytest

# Database
make migrate              # alembic upgrade head
make migrate-new NAME=description   # create autogenerate migration

# Docker (optional, if Docker Desktop + WSL2 integration available)
make up / make down / make logs / make psql
```

**Backend commands** must use `uv run --package finresearch-api ...` so the uv
workspace resolves dependencies correctly. **Frontend commands** must use
`pnpm --filter @finresearch/web ...`.

## Development Rules

- **Issue tracker is the source of truth.** Track every task as an issue
  (Linear `FRA-xx`, or GitHub issue mapped to the same ID).
- **Branch naming**: include the issue ID — `FRA-42-add-ohlcv-sync`,
  `FRA-17/jwt-auth`, etc.
- **Every PR references the issue**: `Fixes FRA-42` or `Implements FRA-42`.
- **Do not implement a feature without acceptance criteria.** Write the criteria
  into the issue first; if missing, ask before coding.
- **Run backend tests before submitting backend changes** (`make test`).
- **Run frontend type checks before submitting frontend changes**
  (`make type-check` and `make lint`).
- **Commit messages**: conventional-commit style —
  `feat(api): add /assets endpoint`, `fix(web): correct price chart axis`,
  `docs: expand agent-design`. End multi-paragraph messages with a blank line
  then the body.
- **No AI co-author attribution.** Never append `Co-Authored-By:` trailers for
  Claude, Codex, ChatGPT, Cursor, or any other AI assistant. Commit messages
  must contain only the human author's content — keep them clean. This rule
  overrides any default that would add such a trailer.
- **One concern per PR.** Don't bundle unrelated changes; reviewers (and future
  you) need to bisect cleanly.
- **Don't commit secrets.** `.env` is git-ignored for a reason. New env vars go
  into `.env.example` with a placeholder, never a real value.

## Branching & Linear Workflow

Task tracking lives in **Linear** (workspace `yunxie`, team `FRA`, project
`FinResearch-Agent`); code lives in **GitHub** (`Caspian-Lin/FinResearch-Agent`).
The two are linked via the Linear GitHub App — **no per-issue repo binding is
needed**. Including the issue ID (`FRA-N`) in a branch name, PR title, or commit
message auto-links it; `Fixes FRA-N` also drives status automation.

### Branch model: `main` + `dev`

- `main` — stable; receives only tested, promoted code.
- `dev` — integration branch; **every PR targets `dev` first**.
- Feature branches cut from `dev`, named `fra-<N>-<slug>` (lowercase), e.g.
  `fra-2-fix-make-lint`.

### End-to-end flow

1. **Create the issue** in Linear under project `FinResearch-Agent`, with
   explicit acceptance criteria (see *Development Rules*). Note its `FRA-N` id.
2. **Cut a branch from `dev`**:
   `git checkout dev && git pull && git checkout -b fra-<N>-<slug>`.
3. **Implement**, then run the quality gates: `make lint && make test`.
4. **Commit** with conventional-commit style (`fix(api): ...`, `feat(web): ...`).
   No `Co-Authored-By:` trailers for AI assistants (see *Development Rules*).
5. **Open a PR targeting `dev`**:
   `gh pr create --base dev --head fra-<N>-<slug> --title "..." --body "...Fixes FRA-N..."`.
   Linear auto-attaches the PR and moves the issue to **In Progress**.
6. **Review & merge to `dev`** (`gh pr merge <N> --merge`). Linear auto-moves
   the issue to **Done**.
7. **Promote to `main`** once `dev` is verified:
   `git checkout main && git pull && git merge dev && git push`.

### Tooling

- `gh` CLI (>=2.94) is installed and authenticated — prefer it over the web UI
  for PRs, reviews, and merges.
- Linear MCP tools are available to the agent for issue/project management.

## Code Conventions

### Python (`apps/api`, `apps/worker`)
- Formatter/linter: **ruff** (line length 100, target py311). Run `make format`.
- Type checker: **mypy strict** (configured in root `pyproject.toml`).
- Pydantic **v2** — use `BaseModel` with type hints, `model_config`, not the v1
  `Config` inner class.
- SQLAlchemy **2.0 style** — `DeclarativeBase`, `Mapped[T]`, `mapped_column`,
  `select()` statements, not legacy `Query`.
- Async DB? Not yet. Sync sessions via `app.db.session.get_db()` FastAPI dependency.
- Tests in `tests/test_*.py`; fixtures in `tests/conftest.py`. Use `pytest.mark`
  for skips/slow/db-requiring tests.

### TypeScript (`apps/web`, `packages/shared`)
- `strict: true` in `tsconfig.json` — do not weaken.
- Prettier: single quotes, trailing commas, 100-char width.
- Shared types/schemas live in `packages/shared`, **not** duplicated in `apps/web`.
- Import path aliases: `@/*` → `apps/web/src/*`, `@finresearch/shared` → the shared package.

### SQL & Schema
- **Never hand-edit the schema.** All DDL goes through Alembic migrations
  (`make migrate-new`). Tables for time-series OHLCV use TimescaleDB hypertables
  via `create_hypertable()` inside the migration's `upgrade()`.
- Migrations must be **reversible** — always implement `downgrade()`.
- Data migrations (backfills) go in a separate revision from schema migrations.

## Domain-Specific Rules — Financial Research & Agents

This is a financial project. These rules are **non-negotiable** and override
convenience.

### Agent safety boundaries (see `docs/agent-design.md`)
1. The LLM Agent **never** connects to real trading/brokerage APIs.
2. The Agent **does not** emit definitive buy/sell recommendations as investment advice.
3. Any strategy code the Agent produces must run via **templates or a sandbox** —
   never free-form `eval`/`exec` of model output.
4. Every generated report **must** include a risk disclaimer and limitations section.
5. Every conclusion **must** be bound to a data window, asset universe, and stated
   assumptions.

### Backtesting integrity (see `docs/backtesting-methodology.md`)
1. **No look-ahead bias.** Factors may only use data visible at decision time.
2. **No survivorship bias.** If unavoidable, document it in the report.
3. **Time-based splits only.** Never random-split financial time series.
4. Every strategy **must** be compared against a baseline (buy-and-hold, equal-weight,
   or QQQ/SPY).
5. **Always show transaction-cost sensitivity** (pre- and post-cost performance).
6. **Record every backtest's parameters** for reproducibility.

### What this project is NOT (non-goals)
- No live trading. No broker order APIs. No high-frequency / minute-bar trading.
- No complex RL trading strategies in the first phase.
- No Kubernetes production deploy. No multi-tenant SaaS.
- **Never** overstate returns or claim the system "beats the market" or "is
  profitable." Marketing copy and README must emphasize methodology and risk,
  not performance. If a backtest result looks too good, suspect a bug first.

## When You're Unsure

- **Ambiguous requirements** → ask (don't guess). Prefer asking over shipping the
  wrong thing in a financial codebase.
- **Touching money / risk / strategy code** → flag the change explicitly in the PR
  description and request a second review.
- **Adding a new dependency** → justify it in the PR. Prefer the stack already in
  `pyproject.toml` / `package.json`.
- **Schema changes** → write the migration, run it locally, verify `\dt` in psql,
  then commit the migration file.
