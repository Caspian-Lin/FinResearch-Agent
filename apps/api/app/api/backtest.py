"""Backtest API — POST trigger + GET status/result + list (FRA-36).

Endpoints
---------
- ``POST /backtest``          create a backtest_run (pending) + enqueue worker (202)
- ``GET  /backtest/{run_id}`` run + metrics + equity/drawdown curves (404 if not owned)
- ``GET  /backtest``          caller's runs, paginated

Mirrors the FRA-8 sync trigger+poll pattern; execution + persistence live in the
worker (FRA-37). Ownership enforced server-side: a run owned by another user is
indistinguishable from a missing one (both 404, no existence leak).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from rq import Queue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models.asset import Asset
from app.models.backtest import (
    PRICE_FIELDS,
    BacktestMetrics,
    BacktestRun,
    EquityCurvePoint,
    Trade,
)
from app.models.user import User
from app.schemas.backtest import (
    BacktestCreateRequest,
    BacktestDetailRead,
    BacktestEnqueueResponse,
    BacktestListResponse,
    BacktestMetricsRead,
    BacktestRunRead,
    EquityCurvePointRead,
    TradeRead,
)
from app.services.sync import get_backtest_queue

router = APIRouter(prefix="/backtest", tags=["backtest"])

DBSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
BacktestQueue = Annotated[Queue, Depends(get_backtest_queue)]

#: registry 策略白名单(API 层快速 422,不浪费 worker slot)。
ALLOWED_STRATEGIES = frozenset({"buy_hold", "equal_weight", "ma_crossover", "momentum", "reversal"})
ALLOWED_REBALANCE = frozenset({"daily", "weekly", "monthly"})
BACKTEST_JOB_TIMEOUT = 600
BACKTEST_RESULT_TTL = 86400
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@router.post(
    "",
    response_model=BacktestEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create + enqueue a backtest run",
)
def create_backtest(
    payload: BacktestCreateRequest,
    db: DBSession,
    current_user: CurrentUser,
    queue: BacktestQueue,
) -> BacktestEnqueueResponse:
    """Validate config, create ``backtest_run`` (pending), enqueue worker.

    Asset existence, strategy/rebalance/price_field allow-lists, and date
    ordering are checked here so bad requests never consume a worker slot.
    """
    if payload.start > payload.end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start must be <= end")
    if payload.strategy_name not in ALLOWED_STRATEGIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"strategy_name must be one of {sorted(ALLOWED_STRATEGIES)}",
        )
    if payload.rebalance not in ALLOWED_REBALANCE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"rebalance must be one of {sorted(ALLOWED_REBALANCE)}",
        )
    if payload.price_field not in PRICE_FIELDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"price_field must be one of {PRICE_FIELDS}",
        )

    # universe assets 必须全部存在。
    found = set(db.scalars(select(Asset.id).where(Asset.id.in_(payload.universe))).all())
    missing = set(payload.universe) - found
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"assets not found: {sorted(str(m) for m in missing)}",
        )

    # benchmark(可选)必须存在(短路:非 None 时才查)。
    if payload.benchmark_asset_id is not None and db.get(Asset, payload.benchmark_asset_id) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"benchmark asset {payload.benchmark_asset_id} not found",
        )

    config_json = {
        "universe": [str(a) for a in payload.universe],
        "start": payload.start.isoformat(),
        "end": payload.end.isoformat(),
        "strategy_name": payload.strategy_name,
        "initial_capital": payload.initial_capital,
        "cost_bps": payload.cost_bps,
        "rebalance": payload.rebalance,
        "price_field": payload.price_field,
        "benchmark": str(payload.benchmark_asset_id) if payload.benchmark_asset_id else None,
        "strategy_params": payload.strategy_params,
    }
    run = BacktestRun(
        user_id=current_user.id,
        name=payload.name,
        strategy_type=payload.strategy_name,
        config_json=config_json,
        benchmark_asset_id=payload.benchmark_asset_id,
        start_date=payload.start,
        end_date=payload.end,
        price_field=payload.price_field,
        status="pending",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # 调度 worker(FRA-37);字符串路径,RQ 在 worker 侧解析(免 import worker)。
    queue.enqueue(
        "worker.tasks.backtest.run_backtest_job",
        str(run.id),
        job_timeout=BACKTEST_JOB_TIMEOUT,
        result_ttl=BACKTEST_RESULT_TTL,
    )
    return BacktestEnqueueResponse(run_id=run.id, status="pending")


@router.get(
    "/{run_id}",
    response_model=BacktestDetailRead,
    summary="Get a backtest run + metrics + curves",
)
def get_backtest(run_id: uuid.UUID, db: DBSession, current_user: CurrentUser) -> BacktestDetailRead:
    """Return run metadata, metrics, equity/drawdown curve, and trades.

    A run owned by another user returns 404 (no existence leak).
    """
    run = _get_owned_run(db, run_id, current_user.id)
    metrics = db.get(BacktestMetrics, run.id)
    curve = list(
        db.scalars(
            select(EquityCurvePoint)
            .where(EquityCurvePoint.backtest_run_id == run.id)
            .order_by(EquityCurvePoint.series_kind, EquityCurvePoint.time)
        ).all()
    )
    trades = list(
        db.scalars(select(Trade).where(Trade.backtest_run_id == run.id).order_by(Trade.time)).all()
    )
    return BacktestDetailRead(
        run=BacktestRunRead.model_validate(run),
        metrics=BacktestMetricsRead.model_validate(metrics) if metrics else None,
        equity_curve=[EquityCurvePointRead.model_validate(p) for p in curve],
        trades=[TradeRead.model_validate(t) for t in trades],
    )


@router.get(
    "",
    response_model=BacktestListResponse,
    summary="List the caller's backtest runs",
)
def list_backtests(
    db: DBSession,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BacktestListResponse:
    """Paginated list of the caller's runs, newest first."""
    total = db.scalar(
        select(func.count()).select_from(BacktestRun).where(BacktestRun.user_id == current_user.id)
    )
    runs = list(
        db.scalars(
            select(BacktestRun)
            .where(BacktestRun.user_id == current_user.id)
            .order_by(BacktestRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return BacktestListResponse(
        items=[BacktestRunRead.model_validate(r) for r in runs],
        total=int(total or 0),
    )


def _get_owned_run(db: Session, run_id: uuid.UUID, user_id: uuid.UUID) -> BacktestRun:
    """Fetch a run scoped to ``user_id`` or raise a uniform 404 (no existence leak)."""
    run = db.scalar(
        select(BacktestRun).where(BacktestRun.id == run_id, BacktestRun.user_id == user_id)
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Backtest run not found.")
    return run
