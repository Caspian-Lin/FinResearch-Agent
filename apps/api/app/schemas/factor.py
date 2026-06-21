"""Pydantic v2 schemas for the factor research API (FRA-56).

对齐 ``packages/shared`` 的 factor 类型(``TimeSeriesPoint`` / ``FactorValue`` /
``ICSummary`` / ``ICResult`` / ``QuantileResult``),使前端无二次转换层。数值字段
用 ``float``(JSON number,而非 ``Decimal`` 字符串 —— 前端图表需要数字,精度损失
对展示可接受,DB 列仍 ``numeric``)。

sensitivity 响应(shared 未定义)沿用 FRA-54 ``SweepSummary`` 形状。每个研究类
响应都带 ``config_snapshot`` —— 完整请求参数快照,保证可复现(§11.3 第 6 条)。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# --- 对齐 shared 的结果类型 --------------------------------------------------


class TimeSeriesPointRead(BaseModel):
    """时序点(time + value),对齐 shared ``TimeSeriesPoint``。

    承载 IC 逐期序列、分层净值、多空价差等时间序列结果。
    """

    time: datetime
    value: float


class ICSummaryRead(BaseModel):
    """IC 统计汇总,对齐 shared ``ICSummary``(FRA-47 / FRA-52)。"""

    mean: float
    icir: float
    t_stat: float
    p_value: float
    n: int
    positive_rate: float


class ICResultRead(BaseModel):
    """IC 评估结果,对齐 shared ``ICResult``:逐期 IC 序列 + 汇总。"""

    series: list[TimeSeriesPointRead]
    summary: ICSummaryRead


class QuantileResultRead(BaseModel):
    """分层回测结果,对齐 shared ``QuantileResult``(FRA-47 / FRA-53)。

    ``quantile_equity`` 的 key = 分层标签(1..N,1 = 因子值最低)。
    """

    quantile_equity: dict[str, list[TimeSeriesPointRead]]
    top_minus_bottom: list[TimeSeriesPointRead]
    monotonicity: float


class FactorValueRead(BaseModel):
    """单条因子值,对齐 shared ``FactorValue``。

    ``params`` 为参数快照;FRA-48 ``factor_values`` 表未持久化 params(因子名已编码
    参数,如 ``momentum_21``),此处默认空 dict。
    """

    asset_id: str
    factor_name: str
    time: datetime
    value: float
    params: dict[str, Any] = Field(default_factory=dict)
    source: str


class ParamImpactRead(BaseModel):
    """sensitivity 单维度影响(FRA-54 ``ParamImpact``),float 序列化。"""

    param: str
    normalized_range: float
    absolute_range: float
    high_impact: bool


# --- 请求 schemas ------------------------------------------------------------


class FactorComputeRequest(BaseModel):
    """``POST /factors/compute`` payload。"""

    model_config = ConfigDict(extra="forbid")

    universe: list[uuid.UUID] = Field(min_length=1)
    source: str
    start: date
    end: date
    price_field: str = "adjusted"
    factor_names: list[str] = Field(min_length=1)


class QuantileBacktestRequest(BaseModel):
    """``POST /factors/quantile-backtest`` payload。"""

    model_config = ConfigDict(extra="forbid")

    universe: list[uuid.UUID] = Field(min_length=1)
    source: str
    start: date
    end: date
    price_field: str = "adjusted"
    factor_name: str
    n_quantiles: int = Field(default=5, ge=1)


class SensitivityRequest(BaseModel):
    """``POST /factors/sensitivity`` payload。

    ``factors`` = 因子类型(momentum / rsi / volatility);``windows`` 可选,缺省用
    ``DEFAULT_FACTOR_WINDOWS``;``top_ks`` / ``quantiles`` 二选一或并存(选股模式)。
    """

    model_config = ConfigDict(extra="forbid")

    universe: list[uuid.UUID] = Field(min_length=1)
    source: str
    start: date
    end: date
    price_field: str = "adjusted"
    factors: list[str] = Field(min_length=1)
    windows: dict[str, list[int]] | None = None
    top_ks: list[int] = Field(default_factory=lambda: [1, 3])
    quantiles: list[int] = Field(default_factory=list)
    n_quantiles: int = 5
    rebalances: list[str] = Field(default_factory=lambda: ["daily", "weekly", "monthly"])
    cost_bands: list[float] = Field(default_factory=lambda: [0.0, 5.0, 10.0, 25.0])


# --- 响应 schemas ------------------------------------------------------------


class FactorComputeResponse(BaseModel):
    """``POST /factors/compute`` 响应。"""

    source: str
    factor_names: list[str]
    rows_written: int
    config_snapshot: dict[str, Any]


class FactorValuesResponse(BaseModel):
    """``GET /factors/values`` 响应。"""

    factor_name: str
    source: str | None
    items: list[FactorValueRead]
    total: int


class ICResponse(BaseModel):
    """``GET /factors/{name}/ic`` 响应。"""

    factor_name: str
    result: ICResultRead
    config_snapshot: dict[str, Any]


class QuantileBacktestResponse(BaseModel):
    """``POST /factors/quantile-backtest`` 响应。"""

    factor_name: str
    result: QuantileResultRead
    config_snapshot: dict[str, Any]


class SensitivityResponse(BaseModel):
    """``POST /factors/sensitivity`` 响应(FRA-54 ``SweepSummary`` 形状)。"""

    metric_table: list[dict[str, Any]]
    param_impacts: list[ParamImpactRead]
    highly_sensitive: bool
    best_net_sharpe: float | None
    worst_net_sharpe: float | None
    config_snapshot: dict[str, Any]
