"""FastAPI application entry point.

Mounts CORS middleware, the ``/health`` and ``/`` meta endpoints, and the
Week 1 routers: auth, assets, ohlcv, quality, sync, and watchlists. Later
weeks add backtesting, factor, agent, and report routers.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.assets import router as assets_router
from app.api.auth import router as auth_router
from app.api.ohlcv import router as ohlcv_router
from app.api.quality import router as quality_router
from app.api.sync import router as sync_router
from app.api.watchlists import router as watchlists_router
from app.core.config import settings

app = FastAPI(
    title="FinResearch Agent API",
    description=(
        "LLM-powered financial research and backtesting system. "
        "Exposes endpoints for asset management, market data sync, "
        "data quality monitoring, backtesting, and research memos."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(assets_router)
app.include_router(ohlcv_router)
app.include_router(quality_router)
app.include_router(sync_router)
app.include_router(watchlists_router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe. Returns ok if the process is up."""
    return {"status": "ok", "service": "finresearch-api", "version": "0.1.0"}


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    """Root redirect helper."""
    return {
        "service": "finresearch-api",
        "docs": "/docs",
        "health": "/health",
    }
