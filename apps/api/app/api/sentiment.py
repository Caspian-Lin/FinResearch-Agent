"""Sentiment research API — news sync / classify / factor / summaries (FRA-70).

把 Week-4 文本情绪能力暴露为 REST 端点,前端 / Agent(Week 5)消费。
类比 FRA-56 factor API:同步计算端点直接返回结果 + ``config_snapshot``;
异步入队端点建 ``BacktestRun`` + 202,``GET /sentiment/jobs/{id}`` 轮询。

错误约定(验收第 1 条):
* 白名单(provider / classifier key 未知)→ 422;
* universe 资产不存在 → 404;
* ``start > end`` → 422;
* 无新闻 / 无 score → 200 + ``status="success_no_data"``(非错误)。
"""

from __future__ import annotations

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
from app.models.news import NewsItem as NewsItemModel
from app.models.news import SentimentScore as SentimentScoreModel
from app.models.user import User
from app.schemas.factor import TimeSeriesPointRead
from app.schemas.sentiment import (
    NewsItemRead,
    NewsListResponse,
    NewsSyncRequest,
    NewsSyncResponse,
    SentimentClassifyResponse,
    SentimentFactorComputeResponse,
    SentimentFactorItemRead,
    SentimentFactorRequest,
    SentimentFactorResponse,
    SentimentJobEnqueueResponse,
    SentimentJobStatusResponse,
    SentimentScoreRead,
    SentimentScoreRequest,
    SentimentScoresResponse,
    SentimentSummariesResponse,
    SentimentSummaryRead,
)
from app.services.sentiment.classify import classify_news_items
from app.services.sentiment.ingest import sync_news
from app.services.sentiment.service import (
    compute_and_store_sentiment_factor,
    compute_sentiment_factor,
    get_sentiment_summaries,
)
from app.services.sync import get_data_queue

router = APIRouter(prefix="/sentiment", tags=["sentiment"])

DBSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
DataQueue = Annotated[Queue, Depends(get_data_queue)]

DEFAULT_LIMIT = 1000
MAX_LIMIT = 10000
SENTIMENT_JOB_TIMEOUT = 600
SENTIMENT_JOB_RESULT_TTL = 86400

#: 异步 job 的 run_kind → worker task dotted path(RQ 按路径解析,免 import worker)。
SENTIMENT_JOB_TASKS = {
    "sentiment_sync_news": "worker.tasks.sentiment.run_sentiment_sync_news_job",
    "sentiment_classify": "worker.tasks.sentiment.run_sentiment_classify_job",
    "sentiment_factor": "worker.tasks.sentiment.run_sentiment_factor_job",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _validate_universe(db: Session, universe: list[uuid.UUID]) -> None:
    found = set(db.scalars(select(Asset.id).where(Asset.id.in_(list(universe)))).all())
    missing = set(universe) - found
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"assets not found: {sorted(str(m) for m in missing)}",
        )


def _require_start_le_end(start: date | datetime, end: date | datetime) -> None:
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start must be <= end")


def _utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _ts_points(series: pd.Series) -> list[TimeSeriesPointRead]:
    clean = series.dropna().sort_index()
    return [
        TimeSeriesPointRead(time=pd.Timestamp(t).to_pydatetime(), value=float(v))
        for t, v in clean.items()
    ]


def _enqueue_sentiment_job(
    db: Session,
    current_user: User,
    queue: Queue,
    *,
    run_kind: str,
    name: str | None,
    config_json: dict[str, Any],
    start: date,
    end: date,
) -> BacktestRun:
    """建 ``BacktestRun``(pending, run_kind, strategy_type='sentiment')+ 入队 worker。

    仿 factor API ``_enqueue_factor_job``:校验已在调用方完成;此处只落 run + 调度。
    """
    run = BacktestRun(
        user_id=current_user.id,
        name=(name or f"{run_kind}-{uuid.uuid4().hex[:8]}")[:255],
        strategy_type="sentiment",
        config_json=config_json,
        benchmark_asset_id=None,
        start_date=start,
        end_date=end,
        price_field="adjusted",
        status="pending",
        run_kind=run_kind,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    queue.enqueue(
        SENTIMENT_JOB_TASKS[run_kind],
        str(run.id),
        job_timeout=SENTIMENT_JOB_TIMEOUT,
        result_ttl=SENTIMENT_JOB_RESULT_TTL,
    )
    return run


# ---------------------------------------------------------------------------
# POST /sentiment/news/sync  (sync)
# ---------------------------------------------------------------------------


@router.post(
    "/news/sync",
    response_model=NewsSyncResponse,
    summary="Sync news for a universe (synchronous)",
)
def sync_news_endpoint(
    payload: NewsSyncRequest, db: DBSession, current_user: CurrentUser
) -> NewsSyncResponse:
    """Fetch news via provider and idempotent-upsert into ``news_items``."""
    _ = current_user
    _require_start_le_end(payload.start, payload.end)
    _validate_universe(db, payload.universe)

    try:
        result = sync_news(
            asset_ids=list(payload.universe),
            start=payload.start,
            end=payload.end,
            provider_key=payload.provider,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    return NewsSyncResponse(
        provider=result["provider"],
        assets=result["assets"],
        fetched=result["fetched"],
        inserted=result["inserted"],
        updated=result["updated"],
        status=result["status"],
        warning=result.get("warning"),
        config_snapshot={
            "universe": [str(a) for a in payload.universe],
            "start": payload.start.isoformat(),
            "end": payload.end.isoformat(),
            "provider": result["provider"],
        },
    )


# ---------------------------------------------------------------------------
# POST /sentiment/news/sync-async  (async)
# ---------------------------------------------------------------------------


@router.post(
    "/news/sync-async",
    response_model=SentimentJobEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a news sync job",
)
def sync_news_async(
    payload: NewsSyncRequest, db: DBSession, current_user: CurrentUser, queue: DataQueue
) -> SentimentJobEnqueueResponse:
    """校验 + 建 ``sentiment_sync_news`` run + 入队(202)。"""
    _require_start_le_end(payload.start, payload.end)
    _validate_universe(db, payload.universe)
    provider = payload.provider
    cfg: dict[str, Any] = {
        "universe": [str(a) for a in payload.universe],
        "start": payload.start.isoformat(),
        "end": payload.end.isoformat(),
        "provider": provider,
    }
    run = _enqueue_sentiment_job(
        db,
        current_user,
        queue,
        run_kind="sentiment_sync_news",
        name=payload.name,
        config_json=cfg,
        start=payload.start.date(),
        end=payload.end.date(),
    )
    return SentimentJobEnqueueResponse(run_id=run.id, run_kind=run.run_kind)


# ---------------------------------------------------------------------------
# GET /sentiment/news
# ---------------------------------------------------------------------------


@router.get(
    "/news",
    response_model=NewsListResponse,
    summary="List persisted news items",
)
def list_news(
    db: DBSession,
    current_user: CurrentUser,
    asset_id: uuid.UUID | None = None,
    source: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> NewsListResponse:
    """Query persisted ``news_items`` rows (time-ascending, capped by ``limit``)."""
    _ = current_user
    stmt = select(NewsItemModel)
    if asset_id is not None:
        stmt = stmt.where(NewsItemModel.asset_id == asset_id)
    if source is not None:
        stmt = stmt.where(NewsItemModel.source == source)
    if start is not None:
        stmt = stmt.where(NewsItemModel.published_at >= start)
    if end is not None:
        stmt = stmt.where(NewsItemModel.published_at < end)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(NewsItemModel.published_at.desc()).limit(limit)).all())
    items = [
        NewsItemRead(
            id=str(r.id),
            asset_id=str(r.asset_id),
            source=r.source,
            published_at=r.published_at,
            headline=r.headline,
            summary=r.summary,
            url=r.url,
        )
        for r in rows
    ]
    return NewsListResponse(items=items, total=int(total))


# ---------------------------------------------------------------------------
# POST /sentiment/score  (sync)
# ---------------------------------------------------------------------------


@router.post(
    "/score",
    response_model=SentimentClassifyResponse,
    summary="Classify news items for a universe (synchronous)",
)
def classify_news_endpoint(
    payload: SentimentScoreRequest, db: DBSession, current_user: CurrentUser
) -> SentimentClassifyResponse:
    """Find news in window → batch classify → idempotent-upsert ``sentiment_scores``."""
    _ = current_user
    _require_start_le_end(payload.start, payload.end)
    _validate_universe(db, payload.universe)

    start_dt = _utc_midnight(payload.start)
    end_dt = _utc_midnight(payload.end) + timedelta(days=1)
    news_ids = list(
        db.scalars(
            select(NewsItemModel.id)
            .where(NewsItemModel.asset_id.in_(list(payload.universe)))
            .where(NewsItemModel.published_at >= start_dt)
            .where(NewsItemModel.published_at < end_dt)
            .order_by(NewsItemModel.published_at)
        ).all()
    )

    try:
        result = classify_news_items(
            news_item_ids=news_ids,
            classifier_key=payload.classifier,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    classifier_used = result.get("classifier") or payload.classifier or "default"
    return SentimentClassifyResponse(
        classifier=classifier_used,
        news=result["news"],
        classified=result["classified"],
        skipped=result["skipped"],
        inserted=result["inserted"],
        updated=result["updated"],
        status=result["status"],
        config_snapshot={
            "universe": [str(a) for a in payload.universe],
            "start": payload.start.isoformat(),
            "end": payload.end.isoformat(),
            "classifier": classifier_used,
            "news_items_found": len(news_ids),
        },
    )


# ---------------------------------------------------------------------------
# POST /sentiment/score-async  (async)
# ---------------------------------------------------------------------------


@router.post(
    "/score-async",
    response_model=SentimentJobEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a sentiment classification job",
)
def classify_news_async(
    payload: SentimentScoreRequest,
    db: DBSession,
    current_user: CurrentUser,
    queue: DataQueue,
) -> SentimentJobEnqueueResponse:
    """校验 + 建 ``sentiment_classify`` run + 入队(202)。"""
    _require_start_le_end(payload.start, payload.end)
    _validate_universe(db, payload.universe)
    cfg: dict[str, Any] = {
        "universe": [str(a) for a in payload.universe],
        "start": payload.start.isoformat(),
        "end": payload.end.isoformat(),
        "classifier": payload.classifier,
    }
    run = _enqueue_sentiment_job(
        db,
        current_user,
        queue,
        run_kind="sentiment_classify",
        name=payload.name,
        config_json=cfg,
        start=payload.start,
        end=payload.end,
    )
    return SentimentJobEnqueueResponse(run_id=run.id, run_kind=run.run_kind)


# ---------------------------------------------------------------------------
# GET /sentiment/scores
# ---------------------------------------------------------------------------


@router.get(
    "/scores",
    response_model=SentimentScoresResponse,
    summary="List persisted sentiment scores",
)
def list_sentiment_scores(
    db: DBSession,
    current_user: CurrentUser,
    asset_id: uuid.UUID | None = None,
    model_name: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> SentimentScoresResponse:
    """Query ``sentiment_scores`` joined with ``news_items`` (time-ascending)."""
    _ = current_user
    stmt = select(
        SentimentScoreModel,
        NewsItemModel.source.label("news_source"),
        NewsItemModel.headline,
        NewsItemModel.summary,
        NewsItemModel.url,
    ).join(NewsItemModel, SentimentScoreModel.news_item_id == NewsItemModel.id)
    if asset_id is not None:
        stmt = stmt.where(SentimentScoreModel.asset_id == asset_id)
    if model_name is not None:
        stmt = stmt.where(SentimentScoreModel.model_name == model_name)
    if start is not None:
        stmt = stmt.where(SentimentScoreModel.published_at >= _utc_midnight(start))
    if end is not None:
        stmt = stmt.where(SentimentScoreModel.published_at < _utc_midnight(end) + timedelta(days=1))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(SentimentScoreModel.published_at.desc()).limit(limit)).all()
    items = [
        SentimentScoreRead(
            id=str(row.SentimentScore.id),
            news_item_id=str(row.SentimentScore.news_item_id),
            asset_id=str(row.SentimentScore.asset_id),
            published_at=row.SentimentScore.published_at,
            model_name=row.SentimentScore.model_name,
            label=row.SentimentScore.label,
            score=float(row.SentimentScore.score),
            confidence=(
                float(row.SentimentScore.confidence)
                if row.SentimentScore.confidence is not None
                else None
            ),
            source=row.news_source,
            headline=row.headline,
            summary=row.summary,
            url=row.url,
        )
        for row in rows
    ]
    return SentimentScoresResponse(items=items, total=int(total))


# ---------------------------------------------------------------------------
# GET /sentiment/factor
# ---------------------------------------------------------------------------


@router.get(
    "/factor",
    response_model=SentimentFactorResponse,
    summary="Compute the daily sentiment factor on-the-fly",
)
def get_sentiment_factor(
    db: DBSession,
    current_user: CurrentUser,
    universe: Annotated[list[uuid.UUID], Query(min_length=1)],
    start: date,
    end: date,
    model_name: str,
) -> SentimentFactorResponse:
    """Compute the daily mean-score sentiment factor (sync, read-only)."""
    _ = current_user
    _require_start_le_end(start, end)
    _validate_universe(db, universe)

    try:
        frame = compute_sentiment_factor(
            db,
            asset_ids=list(universe),
            start=start,
            end=end,
            model_name=model_name,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    items = [
        SentimentFactorItemRead(asset_id=col, values=_ts_points(frame[col]))
        for col in frame.columns
    ]
    return SentimentFactorResponse(
        model_name=model_name,
        items=items,
        config_snapshot={
            "universe": [str(a) for a in universe],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "model_name": model_name,
        },
    )


# ---------------------------------------------------------------------------
# POST /sentiment/factor/compute  (sync, persists)
# ---------------------------------------------------------------------------


@router.post(
    "/factor/compute",
    response_model=SentimentFactorComputeResponse,
    summary="Compute + persist the daily sentiment factor",
)
def compute_sentiment_factor_endpoint(
    payload: SentimentFactorRequest, db: DBSession, current_user: CurrentUser
) -> SentimentFactorComputeResponse:
    """Compute the daily sentiment factor and persist it to ``factor_values``."""
    _ = current_user
    _require_start_le_end(payload.start, payload.end)
    _validate_universe(db, payload.universe)

    try:
        result = compute_and_store_sentiment_factor(
            db,
            universe=list(payload.universe),
            start=payload.start,
            end=payload.end,
            model_name=payload.model_name,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    return SentimentFactorComputeResponse(
        model_name=result["model_name"],
        assets=result["assets"],
        scores_read=result["scores_read"],
        rows_written=result["rows_written"],
        status=result["status"],
        config_snapshot={
            "universe": [str(a) for a in payload.universe],
            "start": payload.start.isoformat(),
            "end": payload.end.isoformat(),
            "model_name": payload.model_name,
        },
    )


# ---------------------------------------------------------------------------
# POST /sentiment/factor/compute-async  (async)
# ---------------------------------------------------------------------------


@router.post(
    "/factor/compute-async",
    response_model=SentimentJobEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a sentiment factor computation job",
)
def compute_sentiment_factor_async(
    payload: SentimentFactorRequest,
    db: DBSession,
    current_user: CurrentUser,
    queue: DataQueue,
) -> SentimentJobEnqueueResponse:
    """校验 + 建 ``sentiment_factor`` run + 入队(202)。"""
    _require_start_le_end(payload.start, payload.end)
    _validate_universe(db, payload.universe)
    cfg: dict[str, Any] = {
        "universe": [str(a) for a in payload.universe],
        "start": payload.start.isoformat(),
        "end": payload.end.isoformat(),
        "model_name": payload.model_name,
    }
    run = _enqueue_sentiment_job(
        db,
        current_user,
        queue,
        run_kind="sentiment_factor",
        name=payload.name,
        config_json=cfg,
        start=payload.start,
        end=payload.end,
    )
    return SentimentJobEnqueueResponse(run_id=run.id, run_kind=run.run_kind)


# ---------------------------------------------------------------------------
# GET /sentiment/summaries
# ---------------------------------------------------------------------------


@router.get(
    "/summaries",
    response_model=SentimentSummariesResponse,
    summary="Get daily sentiment summaries (rich aggregates)",
)
def get_sentiment_summaries_endpoint(
    db: DBSession,
    current_user: CurrentUser,
    universe: Annotated[list[uuid.UUID], Query(min_length=1)],
    start: date,
    end: date,
    model_name: str,
    window_days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> SentimentSummariesResponse:
    """Return per ``(signal_date, asset_id)`` sentiment summaries with label counts."""
    _ = current_user
    _require_start_le_end(start, end)
    _validate_universe(db, universe)

    try:
        summaries = get_sentiment_summaries(
            db,
            asset_ids=list(universe),
            start=start,
            end=end,
            model_name=model_name,
            window_days=window_days,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    items = [
        SentimentSummaryRead(
            asset_id=s.asset_id,
            signal_date=s.signal_date.to_pydatetime(),
            window_start=s.window_start,
            window_end=s.window_end,
            model_name=s.model_name,
            prompt_version=s.prompt_version,
            score=s.score,
            confidence=s.confidence,
            news_count=s.news_count,
            label_counts={str(k): v for k, v in s.label_counts.items()},
            source=s.source,
        )
        for s in summaries
    ]
    return SentimentSummariesResponse(
        model_name=model_name,
        items=items,
        total=len(items),
        config_snapshot={
            "universe": [str(a) for a in universe],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "model_name": model_name,
            "window_days": window_days,
        },
    )


# ---------------------------------------------------------------------------
# GET /sentiment/jobs/{run_id}
# ---------------------------------------------------------------------------


@router.get(
    "/jobs/{run_id}",
    response_model=SentimentJobStatusResponse,
    summary="Poll a sentiment worker job's status + result",
)
def get_sentiment_job(
    run_id: uuid.UUID, db: DBSession, current_user: CurrentUser
) -> SentimentJobStatusResponse:
    """读 sentiment worker job:status + error_message + result_json(轮询用)。

    仅 sentiment worker 三类 run_kind 可见;他人 run / 非 sentiment run 都 404
    (无存在泄露,同 factor ``get_factor_job`` 约定)。
    """
    run = db.scalar(
        select(BacktestRun).where(BacktestRun.id == run_id, BacktestRun.user_id == current_user.id)
    )
    if run is None or run.run_kind not in SENTIMENT_JOB_TASKS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="sentiment job not found.")
    return SentimentJobStatusResponse(
        run_id=run.id,
        name=run.name,
        run_kind=run.run_kind,
        status=run.status,
        error_message=run.error_message,
        result=run.result_json,
        config_snapshot=dict(run.config_json),
    )
