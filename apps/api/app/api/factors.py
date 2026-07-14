"""Factor research API — compute / values / IC / quantile-backtest / sensitivity (FRA-56).

把因子能力暴露为 REST 端点,前端 / Agent(Week 5)消费。除 ``compute``(落
``factor_values``)外,IC / 分层 / 敏感性均为纯计算,同步返回结果 + ``config_snapshot``
(完整参数快照,保证可复现,§11.3 第 6 条)。

防前视:所有计算复用 Week-2/3 的防前视原语 —— ``load_prices`` 无 forward-fill,
因子滚动窗口、IC 评估的 forward_returns 仅评估用、分层回测的引擎 ``shift(1)`` 边界。

错误约定(验收第 1 条):
* 白名单(factor_name / factor type / rebalance / price_field)违例 → 422;
* universe 资产不存在 → 404;
* ``start > end`` → 422;
* 数据不足(``load_prices`` / 计算抛 ``ValueError``)→ 422。
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from rq import Queue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models.asset import Asset
from app.models.backtest import BacktestRun
from app.models.factor import FactorValue
from app.models.user import User
from app.schemas.factor import (
    FactorComputeRequest,
    FactorComputeResponse,
    FactorJobEnqueueResponse,
    FactorJobStatusResponse,
    FactorRankingSnapshotItemRead,
    FactorRankingSnapshotResponse,
    FactorValueRead,
    FactorValuesResponse,
    ICResponse,
    ICResultRead,
    ICSummaryRead,
    ParamImpactRead,
    QuantileBacktestRequest,
    QuantileBacktestResponse,
    QuantileResultRead,
    SensitivityRequest,
    SensitivityResponse,
    TimeSeriesPointRead,
)
from app.services.backtest.prices import load_prices
from app.services.backtest.sensitivity import (
    factor_sensitivity_configs,
    run_sweep,
    summarize_sweep,
)
from app.services.backtest.types import BacktestConfig, PriceField, RebalanceFreq
from app.services.factors.evaluation import evaluate_ic, forward_returns
from app.services.factors.quantile import QuantileBacktester
from app.services.factors.ranking import cross_sectional_rank, quantile_bucket, zscore
from app.services.factors.service import FACTOR_REGISTRY, compute_and_store_factors
from app.services.sync import get_backtest_queue

router = APIRouter(prefix="/factors", tags=["factors"])

DBSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
BacktestQueue = Annotated[Queue, Depends(get_backtest_queue)]

#: 因子白名单(已注册的因子名,如 momentum_21 / rsi_14)。
ALLOWED_FACTORS = frozenset(FACTOR_REGISTRY)
#: 敏感性 sweep 的因子类型白名单。
ALLOWED_FACTOR_TYPES = frozenset({"momentum", "rsi", "volatility"})
ALLOWED_REBALANCE = frozenset({"daily", "weekly", "monthly"})
DEFAULT_LIMIT = 1000
MAX_LIMIT = 10000
#: factor worker job RQ 调度参数(同 backtest,复用 backtest 队列)。
FACTOR_JOB_TIMEOUT = 600
FACTOR_JOB_RESULT_TTL = 86400
#: 异步 job 的 run_kind → worker task dotted path(RQ 按路径解析,免 import worker)。
FACTOR_JOB_TASKS = {
    "factor_compute": "worker.tasks.factor.run_factor_compute_job",
    "factor_quantile": "worker.tasks.factor.run_factor_quantile_job",
    "factor_sweep": "worker.tasks.factor.run_factor_sweep_job",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _price_field_or_422(price_field: str) -> PriceField:
    try:
        return PriceField(price_field)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"price_field must be one of {[p.value for p in PriceField]}",
        ) from None


def _validate_universe(db: Session, universe: list[uuid.UUID]) -> None:
    found = set(db.scalars(select(Asset.id).where(Asset.id.in_(list(universe)))).all())
    missing = set(universe) - found
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"assets not found: {sorted(str(m) for m in missing)}",
        )


def _require_start_le_end(start: date, end: date) -> None:
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start must be <= end")


def _insufficient(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _ts_points(series: pd.Series) -> list[TimeSeriesPointRead]:
    """时序 Series(可能含 NaN)→ 非 NaN TimeSeriesPoint 列表(按 index 升序)。"""
    clean = series.dropna().sort_index()
    return [
        TimeSeriesPointRead(time=pd.Timestamp(t).to_pydatetime(), value=float(v))
        for t, v in clean.items()
    ]


def _utc_midnight(d: date) -> datetime:
    """A date as UTC midnight, matching price/factor frame indexes."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


# ---------------------------------------------------------------------------
# POST /factors/compute
# ---------------------------------------------------------------------------


@router.post(
    "/compute",
    response_model=FactorComputeResponse,
    summary="Compute + persist factor values for a universe",
)
def compute_factors_endpoint(
    payload: FactorComputeRequest, db: DBSession, current_user: CurrentUser
) -> FactorComputeResponse:
    """Load prices → compute factors → idempotent upsert into ``factor_values``."""
    _ = current_user  # 登录即可;factor_values 无 user 归属
    _require_start_le_end(payload.start, payload.end)
    pf = _price_field_or_422(payload.price_field)
    bad = [n for n in payload.factor_names if n not in ALLOWED_FACTORS]
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown factor_names {bad}; allowed: {sorted(ALLOWED_FACTORS)}",
        )
    _validate_universe(db, payload.universe)

    try:
        rows = compute_and_store_factors(
            db,
            universe=payload.universe,
            source=payload.source,
            start=payload.start,
            end=payload.end,
            price_field=pf,
            factor_names=payload.factor_names,
        )
    except ValueError as e:
        raise _insufficient(f"insufficient price data: {e}") from e

    return FactorComputeResponse(
        source=payload.source,
        factor_names=payload.factor_names,
        rows_written=rows,
        config_snapshot={
            "universe": [str(a) for a in payload.universe],
            "source": payload.source,
            "start": payload.start.isoformat(),
            "end": payload.end.isoformat(),
            "price_field": payload.price_field,
            "factor_names": payload.factor_names,
        },
    )


# ---------------------------------------------------------------------------
# GET /factors/values
# ---------------------------------------------------------------------------


@router.get(
    "/values",
    response_model=FactorValuesResponse,
    summary="List persisted factor values",
)
def list_factor_values(
    factor_name: str,
    db: DBSession,
    current_user: CurrentUser,
    source: str | None = None,
    asset_id: uuid.UUID | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> FactorValuesResponse:
    """Query persisted ``factor_values`` rows (time-ascending, capped by ``limit``)."""
    _ = current_user
    stmt = select(FactorValue).where(FactorValue.factor_name == factor_name)
    if source is not None:
        stmt = stmt.where(FactorValue.source == source)
    if asset_id is not None:
        stmt = stmt.where(FactorValue.asset_id == asset_id)
    if start is not None:
        stmt = stmt.where(
            FactorValue.time >= datetime(start.year, start.month, start.day, tzinfo=UTC)
        )
    if end is not None:
        stmt = stmt.where(
            FactorValue.time
            < datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(FactorValue.time).limit(limit)).all())
    items = [
        FactorValueRead(
            asset_id=str(r.asset_id),
            factor_name=r.factor_name,
            time=r.time,
            value=float(r.value),
            source=r.source,
        )
        for r in rows
    ]
    return FactorValuesResponse(
        factor_name=factor_name, source=source, items=items, total=int(total)
    )


# ---------------------------------------------------------------------------
# GET /factors/{factor_name}/ic
# ---------------------------------------------------------------------------


@router.get(
    "/{factor_name}/snapshot",
    response_model=FactorRankingSnapshotResponse,
    summary="Get a cross-sectional factor ranking snapshot",
)
def get_factor_ranking_snapshot(
    factor_name: str,
    db: DBSession,
    current_user: CurrentUser,
    universe: Annotated[list[uuid.UUID], Query(min_length=1)],
    source: str,
    start: date,
    end: date,
    snapshot_date: date | None = None,
    n_quantiles: Annotated[int, Query(ge=1)] = 5,
    price_field: str = "adjusted",
) -> FactorRankingSnapshotResponse:
    """Raw value + rank pct + z-score + bucket for one factor cross-section.

    ``snapshot_date`` is exact when provided: no forward/back fill. Without it,
    the endpoint selects the latest date inside ``[start, end]`` with enough
    non-NaN factor values to compute ranks and ``n_quantiles`` buckets.
    """
    _ = current_user
    if factor_name not in ALLOWED_FACTORS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown factor {factor_name!r}; allowed: {sorted(ALLOWED_FACTORS)}",
        )
    _require_start_le_end(start, end)
    if snapshot_date is not None and not (start <= snapshot_date <= end):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="snapshot_date must be within [start, end]",
        )
    pf = _price_field_or_422(price_field)
    _validate_universe(db, universe)

    assets = list(db.scalars(select(Asset).where(Asset.id.in_(list(universe)))).all())
    symbol_by_id = {str(asset.id): asset.symbol for asset in assets}

    try:
        prices = load_prices(db, universe, source, start, end, pf)
        factor = FACTOR_REGISTRY[factor_name](prices)
    except ValueError as e:
        raise _insufficient(f"insufficient price data: {e}") from e

    if snapshot_date is None:
        valid_counts = factor.notna().sum(axis=1)
        required = max(2, n_quantiles)
        candidates = factor.index[valid_counts >= required]
        snapshot_ts = pd.Timestamp(candidates[-1]).to_pydatetime() if len(candidates) else None
    else:
        requested_ts = pd.Timestamp(_utc_midnight(snapshot_date))
        if requested_ts in factor.index:
            row = factor.loc[requested_ts]
            snapshot_ts = (
                requested_ts.to_pydatetime()
                if int(row.notna().sum()) >= max(2, n_quantiles)
                else None
            )
        else:
            snapshot_ts = None

    items: list[FactorRankingSnapshotItemRead] = []
    if snapshot_ts is not None:
        selected = pd.Timestamp(snapshot_ts)
        frame = factor.loc[[selected]]
        ranks = cross_sectional_rank(frame).iloc[0]
        zs = zscore(frame).iloc[0]
        buckets = quantile_bucket(frame, n_quantiles=n_quantiles).iloc[0]
        values = frame.iloc[0]
        for asset_col, value in values.dropna().items():
            bucket = buckets.get(asset_col)
            rank_pct = ranks.get(asset_col)
            if pd.isna(bucket) or pd.isna(rank_pct):
                continue
            z = zs.get(asset_col)
            items.append(
                FactorRankingSnapshotItemRead(
                    asset_id=str(asset_col),
                    symbol=symbol_by_id.get(str(asset_col), str(asset_col)),
                    factor_value=float(value),
                    rank_pct=float(rank_pct),
                    z_score=None if pd.isna(z) else float(z),
                    quantile_bucket=int(bucket),
                )
            )
        items.sort(key=lambda item: item.rank_pct, reverse=True)

    return FactorRankingSnapshotResponse(
        factor_name=factor_name,
        source=source,
        snapshot_time=snapshot_ts,
        requested_date=snapshot_date,
        n_quantiles=n_quantiles,
        items=items,
        total=len(items),
        config_snapshot={
            "universe": [str(a) for a in universe],
            "source": source,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "snapshot_date": snapshot_date.isoformat() if snapshot_date is not None else None,
            "n_quantiles": n_quantiles,
            "price_field": price_field,
            "factor_name": factor_name,
        },
    )


@router.get(
    "/{factor_name}/ic",
    response_model=ICResponse,
    summary="Evaluate a factor's information coefficient",
)
def get_factor_ic(
    factor_name: str,
    db: DBSession,
    current_user: CurrentUser,
    universe: Annotated[list[uuid.UUID], Query(min_length=2)],
    source: str,
    start: date,
    end: date,
    horizon: Annotated[int, Query(ge=1)] = 5,
    price_field: str = "adjusted",
) -> ICResponse:
    """Cross-sectional Spearman IC of ``factor_name`` vs ``horizon``-day forward returns."""
    _ = current_user
    if factor_name not in ALLOWED_FACTORS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown factor {factor_name!r}; allowed: {sorted(ALLOWED_FACTORS)}",
        )
    _require_start_le_end(start, end)
    pf = _price_field_or_422(price_field)
    _validate_universe(db, universe)

    try:
        prices = load_prices(db, universe, source, start, end, pf)
        factor = FACTOR_REGISTRY[factor_name](prices)
        fwd = forward_returns(prices, horizon)
        result = evaluate_ic(factor, fwd)
    except ValueError as e:
        raise _insufficient(f"insufficient price data: {e}") from e

    return ICResponse(
        factor_name=factor_name,
        result=ICResultRead(
            series=_ts_points(result.series),
            summary=ICSummaryRead(**dataclasses.asdict(result.summary)),
        ),
        config_snapshot={
            "universe": [str(a) for a in universe],
            "source": source,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "horizon": horizon,
            "price_field": price_field,
            "factor_name": factor_name,
        },
    )


# ---------------------------------------------------------------------------
# POST /factors/quantile-backtest
# ---------------------------------------------------------------------------


@router.post(
    "/quantile-backtest",
    response_model=QuantileBacktestResponse,
    summary="Run a stratified (quantile) backtest",
)
def quantile_backtest(
    payload: QuantileBacktestRequest, db: DBSession, current_user: CurrentUser
) -> QuantileBacktestResponse:
    """Split universe into N buckets by factor value; return per-bucket equity + spread."""
    _ = current_user
    if payload.factor_name not in ALLOWED_FACTORS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown factor {payload.factor_name!r}; allowed: {sorted(ALLOWED_FACTORS)}",
        )
    _require_start_le_end(payload.start, payload.end)
    pf = _price_field_or_422(payload.price_field)
    _validate_universe(db, payload.universe)

    try:
        prices = load_prices(db, payload.universe, payload.source, payload.start, payload.end, pf)
        factor = FACTOR_REGISTRY[payload.factor_name](prices)
        result = QuantileBacktester().run(factor, prices, payload.n_quantiles)
    except ValueError as e:
        raise _insufficient(f"insufficient price data: {e}") from e

    quantile_equity: dict[str, list[TimeSeriesPointRead]] = {
        str(col): _ts_points(result.quantile_equity[col]) for col in result.quantile_equity.columns
    }
    return QuantileBacktestResponse(
        factor_name=payload.factor_name,
        result=QuantileResultRead(
            quantile_equity=quantile_equity,
            top_minus_bottom=_ts_points(result.top_minus_bottom),
            monotonicity=float(result.monotonicity),
        ),
        config_snapshot={
            "universe": [str(a) for a in payload.universe],
            "source": payload.source,
            "start": payload.start.isoformat(),
            "end": payload.end.isoformat(),
            "price_field": payload.price_field,
            "factor_name": payload.factor_name,
            "n_quantiles": payload.n_quantiles,
        },
    )


# ---------------------------------------------------------------------------
# POST /factors/sensitivity
# ---------------------------------------------------------------------------


@router.post(
    "/sensitivity",
    response_model=SensitivityResponse,
    summary="Run a factor parameter/cost sensitivity sweep",
)
def factor_sensitivity(
    payload: SensitivityRequest, db: DBSession, current_user: CurrentUser
) -> SensitivityResponse:
    """Sweep factor × window × top_k/quantile × rebalance × cost; return the summary grid."""
    _ = current_user
    _require_start_le_end(payload.start, payload.end)
    pf = _price_field_or_422(payload.price_field)
    bad_factors = [f for f in payload.factors if f not in ALLOWED_FACTOR_TYPES]
    if bad_factors:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown factor types {bad_factors}; allowed: {sorted(ALLOWED_FACTOR_TYPES)}",
        )
    bad_rb = [r for r in payload.rebalances if r not in ALLOWED_REBALANCE]
    if bad_rb:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown rebalances {bad_rb}; allowed: {sorted(ALLOWED_REBALANCE)}",
        )
    _validate_universe(db, payload.universe)

    base = BacktestConfig(
        universe=tuple(str(a) for a in payload.universe),
        start=payload.start,
        end=payload.end,
        strategy_name="factor",
        price_field=pf,
        rebalance=RebalanceFreq.DAILY,
    )
    try:
        configs = factor_sensitivity_configs(
            base,
            factors=payload.factors,
            windows=payload.windows,
            top_ks=payload.top_ks,
            quantiles=payload.quantiles,
            n_quantiles=payload.n_quantiles,
            rebalances=payload.rebalances,
            cost_bands=payload.cost_bands,
        )
        prices = load_prices(db, payload.universe, payload.source, payload.start, payload.end, pf)
        points = run_sweep(prices, configs)
        summary = summarize_sweep(points)
    except ValueError as e:
        raise _insufficient(f"insufficient price data: {e}") from e

    return SensitivityResponse(
        metric_table=summary.metric_table,
        param_impacts=[
            ParamImpactRead(
                param=i.param,
                normalized_range=i.normalized_range,
                absolute_range=i.absolute_range,
                high_impact=i.high_impact,
            )
            for i in summary.param_impacts
        ],
        highly_sensitive=summary.highly_sensitive,
        best_net_sharpe=summary.best_net_sharpe,
        worst_net_sharpe=summary.worst_net_sharpe,
        config_snapshot={
            "universe": [str(a) for a in payload.universe],
            "source": payload.source,
            "start": payload.start.isoformat(),
            "end": payload.end.isoformat(),
            "price_field": payload.price_field,
            "factors": payload.factors,
            "windows": payload.windows,
            "top_ks": payload.top_ks,
            "quantiles": payload.quantiles,
            "n_quantiles": payload.n_quantiles,
            "rebalances": payload.rebalances,
            "cost_bands": payload.cost_bands,
        },
    )


# ---------------------------------------------------------------------------
# FRA-57: 异步 worker 入队 + 状态轮询
# ---------------------------------------------------------------------------


def _enqueue_factor_job(
    db: Session,
    current_user: User,
    queue: Queue,
    *,
    run_kind: str,
    name: str | None,
    config_json: dict[str, Any],
    start: date,
    end: date,
    price_field: str,
) -> BacktestRun:
    """建 ``BacktestRun``(pending, run_kind, strategy_type='factor')+ 入队 worker。

    仿 backtest API ``create_backtest``:校验已在调用方完成(API 层快速 422,不浪费
    worker slot);此处只落 run + 调度。返回新建的 run(pending),worker 执行后改状态。
    """
    run = BacktestRun(
        user_id=current_user.id,
        name=(name or f"{run_kind}-{uuid.uuid4().hex[:8]}")[:255],
        strategy_type="factor",
        config_json=config_json,
        benchmark_asset_id=None,
        start_date=start,
        end_date=end,
        price_field=price_field,
        status="pending",
        run_kind=run_kind,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    # 字符串路径,RQ 在 worker 侧解析(免 import worker,同 backtest 调度)。
    queue.enqueue(
        FACTOR_JOB_TASKS[run_kind],
        str(run.id),
        job_timeout=FACTOR_JOB_TIMEOUT,
        result_ttl=FACTOR_JOB_RESULT_TTL,
    )
    return run


@router.post(
    "/compute-async",
    response_model=FactorJobEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a batch factor computation job",
)
def compute_factors_async(
    payload: FactorComputeRequest, db: DBSession, current_user: CurrentUser, queue: BacktestQueue
) -> FactorJobEnqueueResponse:
    """校验 + 建 ``factor_compute`` run + 入队(202);``GET /factors/jobs/{id}`` 轮询结果。"""
    _require_start_le_end(payload.start, payload.end)
    pf = _price_field_or_422(payload.price_field)
    bad = [n for n in payload.factor_names if n not in ALLOWED_FACTORS]
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown factor_names {bad}; allowed: {sorted(ALLOWED_FACTORS)}",
        )
    _validate_universe(db, payload.universe)
    cfg = {
        "universe": [str(a) for a in payload.universe],
        "source": payload.source,
        "start": payload.start.isoformat(),
        "end": payload.end.isoformat(),
        "price_field": payload.price_field,
        "factor_names": payload.factor_names,
    }
    run = _enqueue_factor_job(
        db,
        current_user,
        queue,
        run_kind="factor_compute",
        name=payload.name,
        config_json=cfg,
        start=payload.start,
        end=payload.end,
        price_field=pf.value,
    )
    return FactorJobEnqueueResponse(run_id=run.id, run_kind=run.run_kind)


@router.post(
    "/quantile-backtest-async",
    response_model=FactorJobEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a stratified (quantile) backtest job",
)
def quantile_backtest_async(
    payload: QuantileBacktestRequest,
    db: DBSession,
    current_user: CurrentUser,
    queue: BacktestQueue,
) -> FactorJobEnqueueResponse:
    """校验 + 建 ``factor_quantile`` run + 入队(202)。"""
    if payload.factor_name not in ALLOWED_FACTORS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown factor {payload.factor_name!r}; allowed: {sorted(ALLOWED_FACTORS)}",
        )
    _require_start_le_end(payload.start, payload.end)
    pf = _price_field_or_422(payload.price_field)
    _validate_universe(db, payload.universe)
    cfg = {
        "universe": [str(a) for a in payload.universe],
        "source": payload.source,
        "start": payload.start.isoformat(),
        "end": payload.end.isoformat(),
        "price_field": payload.price_field,
        "factor_name": payload.factor_name,
        "n_quantiles": payload.n_quantiles,
    }
    run = _enqueue_factor_job(
        db,
        current_user,
        queue,
        run_kind="factor_quantile",
        name=payload.name,
        config_json=cfg,
        start=payload.start,
        end=payload.end,
        price_field=pf.value,
    )
    return FactorJobEnqueueResponse(run_id=run.id, run_kind=run.run_kind)


@router.post(
    "/sensitivity-async",
    response_model=FactorJobEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a factor sensitivity sweep job",
)
def factor_sensitivity_async(
    payload: SensitivityRequest,
    db: DBSession,
    current_user: CurrentUser,
    queue: BacktestQueue,
) -> FactorJobEnqueueResponse:
    """校验 + 建 ``factor_sweep`` run + 入队(202)。"""
    _require_start_le_end(payload.start, payload.end)
    pf = _price_field_or_422(payload.price_field)
    bad_factors = [f for f in payload.factors if f not in ALLOWED_FACTOR_TYPES]
    if bad_factors:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown factor types {bad_factors}; allowed: {sorted(ALLOWED_FACTOR_TYPES)}",
        )
    bad_rb = [r for r in payload.rebalances if r not in ALLOWED_REBALANCE]
    if bad_rb:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown rebalances {bad_rb}; allowed: {sorted(ALLOWED_REBALANCE)}",
        )
    _validate_universe(db, payload.universe)
    cfg = {
        "universe": [str(a) for a in payload.universe],
        "source": payload.source,
        "start": payload.start.isoformat(),
        "end": payload.end.isoformat(),
        "price_field": payload.price_field,
        "factors": payload.factors,
        "windows": payload.windows,
        "top_ks": payload.top_ks,
        "quantiles": payload.quantiles,
        "n_quantiles": payload.n_quantiles,
        "rebalances": payload.rebalances,
        "cost_bands": payload.cost_bands,
    }
    run = _enqueue_factor_job(
        db,
        current_user,
        queue,
        run_kind="factor_sweep",
        name=payload.name,
        config_json=cfg,
        start=payload.start,
        end=payload.end,
        price_field=pf.value,
    )
    return FactorJobEnqueueResponse(run_id=run.id, run_kind=run.run_kind)


@router.get(
    "/jobs/{run_id}",
    response_model=FactorJobStatusResponse,
    summary="Poll a factor worker job's status + result",
)
def get_factor_job(
    run_id: uuid.UUID, db: DBSession, current_user: CurrentUser
) -> FactorJobStatusResponse:
    """读 factor worker job:status + error_message + result_json(轮询用)。

    仅 factor worker 三类 run_kind 可见;他人 run / 非 factor run 都 404(无存在泄露,
    同 backtest ``_get_owned_run`` 约定)。
    """
    run = db.scalar(
        select(BacktestRun).where(BacktestRun.id == run_id, BacktestRun.user_id == current_user.id)
    )
    if run is None or run.run_kind not in FACTOR_JOB_TASKS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="factor job not found.")
    return FactorJobStatusResponse(
        run_id=run.id,
        name=run.name,
        run_kind=run.run_kind,
        status=run.status,
        error_message=run.error_message,
        result=run.result_json,
        config_snapshot=dict(run.config_json),
    )
