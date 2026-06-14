# syntax=docker/dockerfile:1.7
# FastAPI image — uses Tsinghua pip mirror for CN network.

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Configure pip mirror (Tsinghua)
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple/ \
 && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn

# Install system dependencies for psycopg, yfinance, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
      ca-certificates \
      libpq-dev \
      git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# ---- Dependency layer (cached unless pyproject.toml changes) ----
FROM base AS deps
COPY apps/api/pyproject.toml ./apps/api/
COPY apps/worker/pyproject.toml ./apps/worker/
COPY pyproject.toml uv.toml ./
RUN uv sync --no-install-project --package finresearch-api

# ---- Development image ----
FROM deps AS dev
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY packages ./packages
COPY infra ./infra

WORKDIR /app/apps/api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
