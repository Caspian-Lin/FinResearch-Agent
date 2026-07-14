"""Comparison runner — technical-only vs technical+sentiment (FRA-71 §14 场景 B).

在同一 ``prices`` / ``config`` / ``sentiment_frame`` 下并行跑两组回测:

* **technical** — 纯技术因子选股(``SentimentTechStrategy`` with ``sentiment_frame=None``),
  等价 FRA-54 ``FactorStrategy``。
* **sentiment_tech** — 技术 + sentiment 融合(overlay 或 combined 模式)。

可选第三组 **sentiment_only**(仅按 sentiment rank 选股),用于解释 sentiment 因子
单独的预测力。

本模块**纯计算**(不碰 DB),返回 :class:`ComparisonResult`;持久化由
``comparison_jobs.execute_comparison_run`` 负责。

防前视:三组回测使用完全相同的 ``prices`` / ``config`` / ``sentiment_frame``,
引擎统一 ``shift(1)`` → 无 look-ahead。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.services.backtest.engine import run_backtest
from app.services.backtest.strategies.sentiment_tech import SentimentTechStrategy
from app.services.backtest.types import BacktestConfig, BacktestResult


@dataclass(slots=True)
class ComparisonResult:
    """Sentiment vs technical comparison results.

    Attributes:
        technical: 纯技术因子回测结果。
        sentiment_tech: 技术 + sentiment 融合回测结果。
        sentiment_only: 仅 sentiment 排名选股回测结果(可选,None 表示未跑)。
    """

    technical: BacktestResult
    sentiment_tech: BacktestResult
    sentiment_only: BacktestResult | None = None


def run_comparison(
    prices: pd.DataFrame,
    sentiment_frame: pd.DataFrame,
    config: BacktestConfig,
    *,
    strategy_params: dict[str, Any],
) -> ComparisonResult:
    """跑 technical-only + technical+sentiment 对照实验(纯计算)。

    Parameters
    ----------
    prices:
        价格宽表(同引擎约定:index = UTC midnight, columns = str(asset_id))。
    sentiment_frame:
        预计算的 sentiment 因子宽表(values = mean score ∈ [-1, 1])。
    config:
        回测配置(universe / dates / cost / rebalance 等)。三组共用。
    strategy_params:
        策略参数(同 ``ComparisonCreateRequest.strategy_params``):
        ``technical_factor`` / ``window`` / ``top_k`` / ``mode`` /
        ``sentiment_threshold`` / ``sentiment_weight`` /
        ``include_sentiment_only``。

    Returns
    -------
    ComparisonResult
        含 technical + sentiment_tech(+ 可选 sentiment_only)三组回测结果。

    Raises
    ------
    ValueError
        prices 为空或 sentiment_frame 为空。
    """
    if prices.shape[0] == 0 or prices.shape[1] == 0:
        raise ValueError("prices must contain at least one asset and one row")
    if sentiment_frame.shape[0] == 0 or sentiment_frame.shape[1] == 0:
        raise ValueError("sentiment_frame must contain at least one asset and one row")

    p = strategy_params
    tech_factor = str(p.get("technical_factor", "momentum"))
    window = int(p.get("window", 63))
    top_k = int(p.get("top_k", 3))
    mode = str(p.get("mode", "overlay"))
    sent_threshold = float(p.get("sentiment_threshold", 0.0))
    sent_weight = float(p.get("sentiment_weight", 0.5))
    include_sentiment_only = bool(p.get("include_sentiment_only", False))

    # --- technical-only (sentiment_frame=None → 纯技术) ---
    tech_strategy = SentimentTechStrategy(
        technical_factor=tech_factor,  # type: ignore[arg-type]
        window=window,
        top_k=top_k,
    )
    tech_result = run_backtest(prices, tech_strategy, config)

    # --- technical + sentiment ---
    sent_tech_strategy = SentimentTechStrategy(
        technical_factor=tech_factor,  # type: ignore[arg-type]
        window=window,
        top_k=top_k,
        mode=mode,  # type: ignore[arg-type]
        sentiment_threshold=sent_threshold,
        sentiment_weight=sent_weight,
        sentiment_frame=sentiment_frame,
    )
    sent_tech_result = run_backtest(prices, sent_tech_strategy, config)

    # --- sentiment-only (optional) ---
    sent_only_result: BacktestResult | None = None
    if include_sentiment_only:
        # Sentiment-only: use sentiment as the sole ranking signal.
        # Set sentiment_weight=1.0 in combined mode → pure sentiment rank.
        sent_only_strategy = SentimentTechStrategy(
            technical_factor=tech_factor,  # type: ignore[arg-type]
            window=window,
            top_k=top_k,
            mode="combined",
            sentiment_weight=1.0,
            sentiment_frame=sentiment_frame,
        )
        sent_only_result = run_backtest(prices, sent_only_strategy, config)

    return ComparisonResult(
        technical=tech_result,
        sentiment_tech=sent_tech_result,
        sentiment_only=sent_only_result,
    )
