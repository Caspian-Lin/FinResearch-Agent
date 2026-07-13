"""Sentiment worker jobs — async sync / classify / factor (FRA-70).

把 FRA-67/68/69 的三类 sentiment 操作包成可异步执行的 *job*:
``run_id → pending → running → success/failed``。状态机复用 FRA-57
``_run_factor_job`` 的同一套(``BacktestRun.status`` + ``error_message`` +
``result_json``),worker ``worker.tasks.sentiment.run_sentiment_*_job`` 仅作
RQ 入口薄封装。

三类 job:
* ``sentiment_sync_news`` — 抓取新闻(FRA-67 ``sync_news``)。
* ``sentiment_classify`` — 批量分类(FRA-68 ``classify_news_items``)。
* ``sentiment_factor`` — 构建日频因子并写入 ``factor_values``(FRA-69)。

防前视不变:全部复用 service 层的防前视原语 —— ``published_at`` 保留原始
时间戳,日频聚合映射到 >= 它的交易日。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import object_session

from app.db.session import SessionLocal
from app.models.backtest import BacktestRun
from app.models.news import NewsItem as NewsItemModel
from app.services.sentiment.classify import classify_news_items as _classify_news_items
from app.services.sentiment.ingest import sync_news as _sync_news
from app.services.sentiment.service import compute_and_store_sentiment_factor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 共享状态机(仿 factors/jobs.py _run_factor_job)
# ---------------------------------------------------------------------------


def _run_sentiment_job(
    run_id: str,
    *,
    expected_kind: str,
    compute: Callable[[BacktestRun], dict[str, Any]],
) -> dict[str, Any]:
    """执行一个 sentiment job 并维护状态机(pending → running → success/failed)。

    仿 :func:`app.services.factors.jobs._run_factor_job`:开 session →
    置 running → 调 ``compute(run)`` 得结果 dict → 置 success + 写 ``result_json``;
    任一异常 rollback 后重读 run 置 failed + ``error_message``(≤500 字符)再 re-raise。
    """
    rid = uuid.UUID(str(run_id))
    db = SessionLocal()
    try:
        run = db.get(BacktestRun, rid)
        if run is None:
            raise ValueError(f"sentiment job run {rid} not found")
        if run.run_kind != expected_kind:
            raise ValueError(f"run {rid} run_kind={run.run_kind!r}, expected {expected_kind!r}")

        run.status = "running"
        run.error_message = None
        db.commit()

        result = compute(run)

        run.status = "success"
        run.result_json = result
        db.commit()

        logger.info("sentiment job run_id=%s kind=%s status=success", rid, expected_kind)
        return {
            "run_id": str(rid),
            "run_kind": expected_kind,
            "status": "success",
            "result": result,
        }
    except Exception as exc:
        db.rollback()
        run = db.get(BacktestRun, rid)
        if run is not None:
            run.status = "failed"
            run.error_message = str(exc)[:500]
            db.commit()
        logger.exception("sentiment job run_id=%s kind=%s failed", rid, expected_kind)
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 三类 job
# ---------------------------------------------------------------------------


def execute_sentiment_sync_news(run_id: str) -> dict[str, Any]:
    """抓取新闻并幂等写入 ``news_items``。

    ``run.config_json`` 需含 ``universe / start / end / provider``
    (FRA-70 ``NewsSyncRequest`` 形状)。
    """
    return _run_sentiment_job(
        run_id,
        expected_kind="sentiment_sync_news",
        compute=_sync_news_job,
    )


def _sync_news_job(run: BacktestRun) -> dict[str, Any]:
    cfg = dict(run.config_json)
    return _sync_news(
        asset_ids=[uuid.UUID(str(a)) for a in cfg["universe"]],
        start=datetime.fromisoformat(str(cfg["start"])),
        end=datetime.fromisoformat(str(cfg["end"])),
        provider_key=cfg.get("provider"),
    )


def execute_sentiment_classify(run_id: str) -> dict[str, Any]:
    """批量分类 news_items 并幂等写入 ``sentiment_scores``。

    ``run.config_json`` 需含 ``universe / start / end / classifier``
    (FRA-70 ``SentimentScoreRequest`` 形状)。Job 先查出窗口内的
    ``news_items`` IDs,再调 ``classify_news_items``。
    """
    return _run_sentiment_job(
        run_id,
        expected_kind="sentiment_classify",
        compute=_classify_job,
    )


def _classify_job(run: BacktestRun) -> dict[str, Any]:
    cfg = dict(run.config_json)
    db = object_session(run)
    assert db is not None

    start_dt = datetime.combine(
        date.fromisoformat(str(cfg["start"])), datetime.min.time(), tzinfo=UTC
    )
    end_dt = datetime.combine(
        date.fromisoformat(str(cfg["end"])) + timedelta(days=1),
        datetime.min.time(),
        tzinfo=UTC,
    )
    universe = [uuid.UUID(str(a)) for a in cfg["universe"]]
    news_ids = list(
        db.scalars(
            select(NewsItemModel.id)
            .where(NewsItemModel.asset_id.in_(universe))
            .where(NewsItemModel.published_at >= start_dt)
            .where(NewsItemModel.published_at < end_dt)
            .order_by(NewsItemModel.published_at)
        ).all()
    )
    return _classify_news_items(
        news_item_ids=news_ids,
        classifier_key=cfg.get("classifier"),
    )


def execute_sentiment_factor(run_id: str) -> dict[str, Any]:
    """构建日频 sentiment factor 并写入 ``factor_values``。

    ``run.config_json`` 需含 ``universe / start / end / model_name``
    (FRA-70 ``SentimentFactorRequest`` 形状)。
    """
    return _run_sentiment_job(
        run_id,
        expected_kind="sentiment_factor",
        compute=_factor_job,
    )


def _factor_job(run: BacktestRun) -> dict[str, Any]:
    cfg = dict(run.config_json)
    db = object_session(run)
    assert db is not None
    return compute_and_store_sentiment_factor(
        db,
        universe=[uuid.UUID(str(a)) for a in cfg["universe"]],
        start=date.fromisoformat(str(cfg["start"])),
        end=date.fromisoformat(str(cfg["end"])),
        model_name=str(cfg["model_name"]),
    )
