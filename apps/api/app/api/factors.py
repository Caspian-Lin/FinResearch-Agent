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
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models.asset import Asset
from app.models.factor import FactorValue
from app.models.user import User
from app.schemas.factor import (
    FactorComputeRequest,
    FactorComputeResponse,
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
from app.services.factors.service import FACTOR_REGISTRY, compute_and_store_factors

router = APIRouter(prefix="/factors", tags=["factors"])

DBSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

#: 因子白名单(已注册的因子名,如 momentum_21 / rsi_14)。
ALLOWED_FACTORS = frozenset(FACTOR_REGISTRY)
#: 敏感性 sweep 的因子类型白名单。
ALLOWED_FACTOR_TYPES = frozenset({"momentum", "rsi", "volatility"})
ALLOWED_REBALANCE = frozenset({"daily", "weekly", "monthly"})
DEFAULT_LIMIT = 1000
MAX_LIMIT = 10000


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
