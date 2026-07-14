"""Pydantic v2 schemas for the sentiment API (FRA-70).

对齐 ``packages/shared`` 的 sentiment 类型(``NewsItem`` / ``SentimentScore`` /
``SentimentSummary``)与 factor API 的 async-job schemas(``FactorJobEnqueueResponse``
/ ``FactorJobStatusResponse``),使前端无二次转换层。数值字段用 ``float``
(JSON number),时间字段用 ``datetime``(ISO 8601 字符串)。

每个研究类响应都带 ``config_snapshot`` —— 完整请求参数快照,保证可复现
(§11.3 第 6 条)。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.factor import TimeSeriesPointRead

# --- 对齐 shared 的结果类型 --------------------------------------------------


class NewsItemRead(BaseModel):
    """单条新闻,对齐 shared ``NewsItem``(只含展示字段,排除 raw_payload)。"""

    id: str
    asset_id: str
    source: str
    published_at: datetime
    headline: str
    summary: str | None = None
    url: str | None = None


class SentimentScoreRead(BaseModel):
    """单条分类结果,对齐 shared ``SentimentScore``(joined news_items 展示字段)。"""

    id: str
    news_item_id: str
    asset_id: str
    published_at: datetime
    model_name: str
    label: str
    score: float
    confidence: float | None = None
    source: str
    headline: str
    summary: str | None = None
    url: str | None = None


class SentimentSummaryRead(BaseModel):
    """某资产某决策日的情绪聚合,对齐 shared ``SentimentSummary``。"""

    asset_id: str
    signal_date: datetime
    window_start: datetime
    window_end: datetime
    model_name: str
    prompt_version: str
    score: float | None = None
    confidence: float | None = None
    news_count: int
    label_counts: dict[str, int] = Field(default_factory=dict)
    source: str = "computed"


# --- 请求 schemas ------------------------------------------------------------


class NewsSyncRequest(BaseModel):
    """``POST /sentiment/news/sync`` payload。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    universe: list[uuid.UUID] = Field(min_length=1)
    start: datetime
    end: datetime
    provider: str | None = None


class SentimentScoreRequest(BaseModel):
    """``POST /sentiment/score`` payload。

    查找 ``[start, end]`` 内 universe 的 news_items 并批量分类。
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    universe: list[uuid.UUID] = Field(min_length=1)
    start: date
    end: date
    classifier: str | None = None


class SentimentFactorRequest(BaseModel):
    """``POST /sentiment/factor/compute`` payload。

    计算日频 sentiment factor 并持久化到 ``factor_values``。
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    universe: list[uuid.UUID] = Field(min_length=1)
    start: date
    end: date
    model_name: str


# --- 响应 schemas ------------------------------------------------------------


class NewsListResponse(BaseModel):
    """``GET /sentiment/news`` 响应。"""

    items: list[NewsItemRead]
    total: int


class NewsSyncResponse(BaseModel):
    """``POST /sentiment/news/sync`` 响应。"""

    provider: str
    assets: int
    fetched: int
    inserted: int
    updated: int
    status: str
    warning: str | None = None
    config_snapshot: dict[str, Any]


class SentimentScoresResponse(BaseModel):
    """``GET /sentiment/scores`` 响应。"""

    items: list[SentimentScoreRead]
    total: int


class SentimentClassifyResponse(BaseModel):
    """``POST /sentiment/score`` 响应。"""

    classifier: str | None
    news: int
    classified: int
    skipped: int
    inserted: int
    updated: int
    status: str
    config_snapshot: dict[str, Any]


class SentimentFactorItemRead(BaseModel):
    """一个资产的日频 sentiment factor 序列。"""

    asset_id: str
    values: list[TimeSeriesPointRead]


class SentimentFactorResponse(BaseModel):
    """``GET /sentiment/factor`` 响应。"""

    model_name: str
    items: list[SentimentFactorItemRead]
    config_snapshot: dict[str, Any]


class SentimentFactorComputeResponse(BaseModel):
    """``POST /sentiment/factor/compute`` 响应。"""

    model_name: str
    assets: int
    scores_read: int
    rows_written: int
    status: str
    config_snapshot: dict[str, Any]


class SentimentSummariesResponse(BaseModel):
    """``GET /sentiment/summaries`` 响应。"""

    model_name: str
    items: list[SentimentSummaryRead]
    total: int
    config_snapshot: dict[str, Any]


# --- FRA-70: 异步 worker job schemas ----------------------------------------


class SentimentJobEnqueueResponse(BaseModel):
    """``POST /sentiment/*-async`` 的 202 响应:run 已建(pending)+ 入队。"""

    run_id: uuid.UUID
    run_kind: str
    status: str = "pending"


class SentimentJobStatusResponse(BaseModel):
    """``GET /sentiment/jobs/{run_id}`` 响应:轮询 pending → running → success/failed。"""

    run_id: uuid.UUID
    name: str
    run_kind: str
    status: str
    error_message: str | None
    result: dict[str, Any] | None
    config_snapshot: dict[str, Any]
