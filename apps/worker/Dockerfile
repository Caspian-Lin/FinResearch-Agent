# syntax=docker/dockerfile:1.7
# Worker image — mirrors the api Dockerfile. Uses Tsinghua pip mirror.

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple/ \
 && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
      ca-certificates \
      libpq-dev \
      git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

FROM base AS deps
COPY apps/worker/pyproject.toml ./apps/worker/
COPY apps/api/pyproject.toml ./apps/api/
COPY pyproject.toml uv.toml ./
RUN uv sync --no-install-project --package finresearch-worker

FROM deps AS dev
COPY apps/worker ./apps/worker
COPY apps/api ./apps/api
COPY packages ./packages
COPY infra ./infra

WORKDIR /app/apps/worker
CMD ["python", "-m", "worker.main"]
