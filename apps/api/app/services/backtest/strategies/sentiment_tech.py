"""Sentiment + technical composite strategy (FRA-71, §14 场景 B 对照实验).

在 FRA-54 ``FactorStrategy`` 的基础上叠加 sentiment overlay/filter,验证文本因子
是否改善短期择时表现。支持两种融合模式:

* **overlay** — 技术因子选 top_k,再用 sentiment_threshold 过滤(剔除情绪低于
  阈值的资产),存活者等权做多。
* **combined** — 对技术因子值和 sentiment 值分别做横截面 ``cross_sectional_rank``
  归一化到 [0,1],按 ``sentiment_weight`` 加权后选 top_k。

当 ``sentiment_frame`` 为 ``None`` 时退化为纯技术策略(等价 ``FactorStrategy``),
便于在同一函数内跑 technical-only 对照组。

防前视 / 反双重滞后(同 FRA-30/31/54 口径):策略**不**自行 ``shift``。技术因子
用含 ``t`` 日收盘的窗口算(滚动窗口仅看 ≤t);sentiment frame 的每个 score 已由
FRA-65 ``DailySentimentFactor`` 映射到 >= ``published_at`` 的交易日,引擎统一
``holdings = decision.shift(1)`` 兑现 T+1 执行延迟。

NaN 语义:sentiment 缺覆盖(无新闻)的 cell 保持 NaN(不 forward-fill);overlay
模式下 NaN sentiment 视为不达标(被过滤);combined 模式下 NaN 资产在该日不参与
排名(其 combined score 亦为 NaN → 不被选中)。
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from app.services.factors.momentum import momentum
from app.services.factors.ranking import cross_sectional_rank
from app.services.factors.technical import rsi, volatility

#: 支持的技术因子类型(同 FRA-54 FactorStrategy)。
TechFactorName = Literal["momentum", "rsi", "volatility"]
_TECH_FACTORS: tuple[str, ...] = ("momentum", "rsi", "volatility")

#: 融合模式。
CombineMode = Literal["overlay", "combined"]
_MODES: tuple[str, ...] = ("overlay", "combined")


class SentimentTechStrategy:
    """技术因子 + sentiment 融合选股策略。

    Parameters
    ----------
    technical_factor:
        技术因子类型 —— ``"momentum"`` / ``"rsi"`` / ``"volatility"``。
    window:
        技术因子窗口(交易日);必须为正。
    top_k:
        做多的最强资产数;必须为正。universe 可用资产不足时取可用数。
    mode:
        融合模式 —— ``"overlay"``(技术选股 + 情绪过滤)或 ``"combined"``(排名加权)。
    sentiment_threshold:
        overlay 模式下的情绪阈值 ∈ [-1, 1];sentiment < threshold 的资产被剔除。
        默认 0.0(只保留正面情绪)。
    sentiment_weight:
        combined 模式下 sentiment 的权重 ∈ [0, 1];技术因子权重 = 1 − 此值。
        默认 0.5(等权融合)。
    sentiment_frame:
        预计算的 sentiment 因子宽表(index = UTC midnight, columns = str(asset_id),
        values = mean score ∈ [-1, 1])。``None`` 时退化为纯技术策略。

    Notes
    -----
    * overlay 模式:``selected = tech_top_k AND sentiment >= threshold``;存活者等权。
    * combined 模式:``score = (1-w)*tech_rank + w*sent_rank``;选 score 最高 top_k。
    * 纯技术(sentiment_frame=None):完全等价 FactorStrategy 的 top_k 逻辑。
    * 每日选股不足 → 全现金(行和 = 0)。
    """

    def __init__(
        self,
        technical_factor: TechFactorName = "momentum",
        window: int = 63,
        *,
        top_k: int = 3,
        mode: CombineMode = "overlay",
        sentiment_threshold: float = 0.0,
        sentiment_weight: float = 0.5,
        sentiment_frame: pd.DataFrame | None = None,
    ) -> None:
        if technical_factor not in _TECH_FACTORS:
            raise ValueError(
                f"technical_factor must be one of {_TECH_FACTORS}, got {technical_factor!r}"
            )
        if window <= 0:
            raise ValueError(f"window must be positive (got {window})")
        if top_k <= 0:
            raise ValueError(f"top_k must be positive (got {top_k})")
        if mode not in _MODES:
            raise ValueError(f"mode must be one of {_MODES}, got {mode!r}")
        if not -1.0 <= sentiment_threshold <= 1.0:
            raise ValueError(f"sentiment_threshold must be in [-1, 1] (got {sentiment_threshold})")
        if not 0.0 <= sentiment_weight <= 1.0:
            raise ValueError(f"sentiment_weight must be in [0, 1] (got {sentiment_weight})")

        self._tech_factor: TechFactorName = technical_factor
        self._window = window
        self._top_k = top_k
        self._mode: CombineMode = mode
        self._sentiment_threshold = sentiment_threshold
        self._sentiment_weight = sentiment_weight
        self._sentiment_frame = sentiment_frame

    def weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        tech_values = self._compute_technical(prices)

        if self._sentiment_frame is None:
            selected = self._select_top_k(tech_values)
        else:
            sent = self._align_sentiment(prices)
            if self._mode == "overlay":
                selected = self._overlay_select(tech_values, sent)
            else:
                selected = self._combined_select(tech_values, sent)

        counts = selected.sum(axis=1)
        w = selected.astype("float64").div(counts.replace(0, np.nan), axis=0).fillna(0.0)
        w.columns = [str(c) for c in prices.columns]
        return w

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _compute_technical(self, prices: pd.DataFrame) -> pd.DataFrame:
        if self._tech_factor == "momentum":
            return momentum(prices, self._window)
        if self._tech_factor == "rsi":
            return rsi(prices, period=self._window)
        return volatility(prices, window=self._window)

    def _align_sentiment(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Reindex sentiment frame to prices shape; NaN where no coverage."""
        frame = self._sentiment_frame
        assert frame is not None  # caller guards None
        return frame.reindex(index=prices.index, columns=prices.columns)

    def _select_top_k(self, factor_values: pd.DataFrame) -> pd.DataFrame:
        """Select top_k assets by factor value (rank descending)."""
        ranks = factor_values.rank(axis=1, ascending=False, method="first")
        return ranks.le(self._top_k)

    def _overlay_select(self, tech_values: pd.DataFrame, sentiment: pd.DataFrame) -> pd.DataFrame:
        """Technical top_k AND sentiment >= threshold."""
        tech_selected = self._select_top_k(tech_values)
        # NaN sentiment → filtered out (not eligible).
        sentiment_ok = sentiment.ge(self._sentiment_threshold)
        return tech_selected & sentiment_ok

    def _combined_select(self, tech_values: pd.DataFrame, sentiment: pd.DataFrame) -> pd.DataFrame:
        """Weighted rank-average of technical + sentiment → top_k."""
        w = self._sentiment_weight
        tech_rank = cross_sectional_rank(tech_values, ascending=True)
        sent_rank = cross_sectional_rank(sentiment, ascending=True)
        combined = (1.0 - w) * tech_rank + w * sent_rank
        ranks = combined.rank(axis=1, ascending=False, method="first")
        return ranks.le(self._top_k)
