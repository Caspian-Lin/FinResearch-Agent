"""sync_news RQ task (FRA-67) — thin wrapper.

核心执行逻辑在 ``app.services.sentiment.ingest``(service 层,API / 测试可直接
调,免 import worker 包)。本模块是 RQ 入口:worker 按 dotted path
``worker.tasks.sentiment.sync_news`` 解析调度。

复用 ``data_sync`` 队列(``worker/main.py`` 已监听)—— news 抓取与 OHLCV sync 同
属数据采集,同一 worker 进程即可,无需独立队列。

Args are passed as strings (RQ-serialization friendly); parsed inside. Note:
``app`` 是 apps/api 包(uv workspace member);worker 运行时 import,同
``worker/tasks/ohlcv.py`` 模式。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.services.sentiment.ingest import sync_news as _sync_news


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
