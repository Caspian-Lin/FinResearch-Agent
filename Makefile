.PHONY: help install up down logs ps psql redis-cli migrate migrate-new \
        api-dev web-dev worker-dev lint format type-check test clean \
        docker-build docker-rebuild

# Default target
.DEFAULT_GOAL := help

PYTHON_VERSION := 3.11
UV ?= uv
PNPM ?= pnpm

help: ## Show this help message
	@echo "FinResearch Agent — Makefile targets"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------- Install ----------

install: install-py install-node ## Install all dependencies (Python + Node)

install-py: ## Install Python dependencies via uv (all workspace members)
	$(UV) sync --all-packages

install-node: ## Install Node dependencies via pnpm
	$(PNPM) install

# ---------- Docker orchestration ----------

up: ## Start all services (or specified SERVICE=api)
	docker compose up -d $(SERVICE)

down: ## Stop all services (add -v to wipe volumes)
	docker compose down $(V)

logs: ## Tail service logs (SERVICE=api)
	docker compose logs -f $(SERVICE)

ps: ## Show service status
	docker compose ps

docker-build: ## Build all images
	docker compose build

docker-rebuild: ## Rebuild images without cache
	docker compose build --no-cache

# ---------- Container shells ----------

psql: ## Open psql inside postgres container
	docker compose exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

redis-cli: ## Open redis-cli inside redis container
	docker compose exec redis redis-cli

api-shell: ## Open shell in api container
	docker compose exec api bash

worker-shell: ## Open shell in worker container
	docker compose exec worker bash

# ---------- Database migrations ----------

migrate: ## Apply migrations (alembic upgrade head)
	docker compose exec api alembic -c /app/infra/migrations/alembic.ini upgrade head

migrate-new: ## Create new migration (NAME=add_xxx)
	docker compose exec api alembic -c /app/infra/migrations/alembic.ini revision --autogenerate -m "$(NAME)"

migrate-down: ## Roll back one migration
	docker compose exec api alembic -c /app/infra/migrations/alembic.ini downgrade -1

seed: ## Seed sample asset universe (US + A-share) into the database
	$(UV) run --package finresearch-api python -m app.db.seed

# ---------- Local development ----------

api-dev: ## Run FastAPI locally with reload (no Docker)
	$(UV) run --package finresearch-api \
	  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir apps/api

web-dev: ## Run Vite dev server locally
	$(PNPM) --filter @finresearch/web dev

worker-dev: ## Run RQ worker locally (no Docker, requires Redis)
	$(UV) run --package finresearch-worker python -m worker.main

dev: ## Run api + worker + web together (Ctrl+C stops all three)
	@echo "Starting api (:8000) + worker + web (:5173). Ctrl+C stops all."
	@trap 'kill 0' EXIT; \
	$(UV) run --package finresearch-api uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir apps/api & \
	$(UV) run --package finresearch-worker python -m worker.main & \
	$(PNPM) --filter @finresearch/web dev

# ---------- Quality ----------

lint: ## Lint Python + TypeScript
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(PNPM) -r lint

format: ## Auto-format Python + TypeScript
	$(UV) run ruff format .
	$(UV) run ruff check --fix .
	$(PNPM) -r format

type-check: ## Run TypeScript type checker
	$(PNPM) -r type-check

test: ## Run pytest
	$(UV) run pytest

test-watch: ## Run pytest with watcher
	$(UV) run pytest-watched

# ---------- Cleanup ----------

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name dist -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .vite -exec rm -rf {} + 2>/dev/null || true
