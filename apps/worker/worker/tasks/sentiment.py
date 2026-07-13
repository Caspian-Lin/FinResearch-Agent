"""Sentiment RQ tasks (FRA-67, FRA-68, FRA-69, FRA-70) — thin wrappers.

核心执行逻辑在 ``app.services.sentiment.ingest`` / ``classify`` / ``service``
/ ``jobs`` (service 层,API / 测试可直接调,免 import worker 包)。本模块是 RQ
入口:worker 按 dotted path ``worker.tasks.sentiment.*`` 解析调度。

两类入口:
* **直接调用**(FRA-67/68/69)— 参数为原生类型(strings),service 层自建 session。
* **BacktestRun 状态机**(FRA-70)— 参数为 ``run_id`` 字符串,service 层
  ``jobs.py`` 维护 pending → running → success/failed,结果写入 ``result_json``。

复用 ``data_sync`` 队列(``worker/main.py`` 已监听)—— news 抓取、分类与因子
计算同属数据采集,同一 worker 进程即可,无需独立队列。

Args are passed as strings (RQ-serialization friendly); parsed inside. Note:
``app`` 是 apps/api 包(uv workspace member);worker 运行时 import,同
``worker/tasks/ohlcv.py`` 模式。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from app.db.session import SessionLocal
from app.services.sentiment.classify import classify_news_items as _classify_news_items
from app.services.sentiment.ingest import sync_news as _sync_news
from app.services.sentiment.jobs import (
    execute_sentiment_classify,
    execute_sentiment_factor,
    execute_sentiment_sync_news,
)
from app.services.sentiment.service import compute_and_store_sentiment_factor as _compute_factor


def sync_news(
    asset_ids: list[str],
    start: str,
    end: str,
    provider: str | None = None,
) -> dict[str, Any]:
    """RQ 入口:按 asset universe + window 抓取新闻并幂等写入 ``news_items``。

    Args:
        asset_ids: Asset UUID 字符串列表(RQ 经 Redis 序列化,需原生类型)。
        start: ISO datetime 字符串,窗口起点(半开区间 ``[start, end)``)。
        end: ISO datetime 字符串,窗口终点。
        provider: News provider key;``None`` 走 ``settings.news_provider``。
            未知 key 由 ``get_news_provider`` raise ``ValueError``。

    Returns / Raises: 透传 service 层 :func:`sync_news`(成功返回 status=result
        摘要;preflight 失败 / provider 失败 raise ``ValueError``,RQ 记
        ``exc_info``)。
    """
    return _sync_news(
        asset_ids=[uuid.UUID(a) for a in asset_ids],
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        provider_key=provider,
    )


def classify_news(
    news_item_ids: list[str],
    classifier: str | None = None,
) -> dict[str, Any]:
    """RQ 入口:对 ``news_items`` 批量分类并幂等写入 ``sentiment_scores``。

    Args:
        news_item_ids: NewsItem UUID 字符串列表(RQ 经 Redis 序列化,需原生类型)。
        classifier: Sentiment classifier key;``None`` 走
            ``settings.sentiment_classifier``。未知 key 由
            ``get_sentiment_classifier`` raise ``ValueError``。

    Returns / Raises: 透传 service 层 :func:`classify_news_items`(成功返回
        status=result 摘要;preflight 失败 / classifier 失败 raise
        ``ValueError``,RQ 记 ``exc_info``)。
    """
    return _classify_news_items(
        news_item_ids=[uuid.UUID(nid) for nid in news_item_ids],
        classifier_key=classifier,
    )


def compute_sentiment_factor(
    asset_ids: list[str],
    start: str,
    end: str,
    model_name: str,
) -> dict[str, Any]:
    """RQ 入口:构建日频 sentiment factor 并写入 ``factor_values`` (FRA-69)。

    Args:
        asset_ids: Asset UUID 字符串列表(RQ 经 Redis 序列化,需原生类型)。
        start: ISO date 字符串 (``YYYY-MM-DD``),因子窗口起点(闭区间)。
        end: ISO date 字符串,因子窗口终点(闭区间)。
        model_name: Classifier model name(决定读哪些 ``sentiment_scores`` 行,
            同时写入 ``factor_values.source`` 以区分不同模型的因子值)。

    Returns / Raises: 透传 service 层
        :func:`compute_and_store_sentiment_factor`(成功返回 status=result 摘要;
        preflight 失败 raise ``ValueError``,RQ 记 ``exc_info``)。
    """
    db = SessionLocal()
    try:
        return _compute_factor(
            db,
            universe=[uuid.UUID(a) for a in asset_ids],
            start=date.fromisoformat(start),
            end=date.fromisoformat(end),
            model_name=model_name,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# FRA-70: BacktestRun 状态机入口(接收 run_id,维护 pending → success/failed)
# ---------------------------------------------------------------------------


def run_sentiment_sync_news_job(run_id: str) -> dict[str, Any]:
    """RQ 入口(状态机版):抓取新闻 → 幂等写入 ``news_items`` → 结果写 ``result_json``。

    Args:
        run_id: ``BacktestRun(run_kind='sentiment_sync_news')`` UUID 字符串。
    """
    return execute_sentiment_sync_news(run_id)


def run_sentiment_classify_job(run_id: str) -> dict[str, Any]:
    """RQ 入口(状态机版):批量分类 → 幂等写入 ``sentiment_scores`` → 结果写 ``result_json``。

    Args:
        run_id: ``BacktestRun(run_kind='sentiment_classify')`` UUID 字符串。
    """
    return execute_sentiment_classify(run_id)


def run_sentiment_factor_job(run_id: str) -> dict[str, Any]:
    """RQ 入口(状态机版):构建日频因子 → 写入 ``factor_values`` → 结果写 ``result_json``。

    Args:
        run_id: ``BacktestRun(run_kind='sentiment_factor')`` UUID 字符串。
    """
    return execute_sentiment_factor(run_id)
