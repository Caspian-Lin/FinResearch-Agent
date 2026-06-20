"""Factor-based selection strategy (FRA-54, §14 因子参数敏感性).

通用「因子选股」策略:在每个决策日用某因子值对 universe 横截面排序,选
最强 ``top_k`` 只(或指定 quantile 层)等权做多。参数化因子类型 + 窗口,使
FRA-54 的因子敏感性 sweep 能扫描 ``momentum`` / ``rsi`` / ``volatility`` 的
不同窗口,复用 FRA-28 引擎 + FRA-34 指标。

防前视 / 反双重滞后(同 FRA-30/31 口径):策略**不**自行 ``shift``。因子值用含
``t`` 日收盘的窗口算(滚动/扩展窗口仅看 ``t`` 及更早),引擎统一
``holdings = decision.shift(1)`` 兑现 T+1 执行延迟 → ``t`` 日信号只影响 ``t+1``
及之后的收益,无 look-ahead、不双重滞后。

因子计算复用 Week-3 因子模块:FRA-49 ``momentum``、FRA-50 ``rsi`` /
``volatility``、FRA-51 ``quantile_bucket``(quantile 选股模式)。

空头:``Strategy`` 协议约束每行权重和 ∈ ``[0, 1]``,不支持负权重 → 只做多
(top_k 或 quantile 层)。多空组合(top-minus-bottom)由 FRA-53 分层回测覆盖,
本策略面向「因子多头组合在不同窗口 / 成本下的稳健性」敏感性研究。
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from app.services.factors.momentum import momentum
from app.services.factors.ranking import quantile_bucket
from app.services.factors.technical import rsi, volatility

#: 支持的因子类型(FRA-54 因子维度)。值对应 ``strategy_params["factor"]``。
FactorName = Literal["momentum", "rsi", "volatility"]
_FACTOR_NAMES: tuple[str, ...] = ("momentum", "rsi", "volatility")


class FactorStrategy:
    """因子选股:用因子值选 top_k(或指定 quantile 层)资产等权做多。

    Parameters
    ----------
    factor:
        因子类型 —— ``"momentum"``(FRA-49,参数 ``window`` = lookback)、
        ``"rsi"``(FRA-50,``window`` = period)、``"volatility"``(FRA-50,
        ``window`` = 年化波动窗口)。
    window:
        因子窗口(交易日);必须为正。约 21=1M、63=3M、126=6M(momentum),
        7/14(rsi),20/63(volatility)。
    top_k:
        top_k 模式下做多的最强资产数(因子值最大的 ``top_k`` 只);与 ``quantile``
        互斥。universe 可用资产不足时取可用数。必须为正。
    quantile:
        quantile 模式下做多的分位层(1 = 最低因子值,N = 最高);与 ``top_k``
        互斥。必须在 ``[1, n_quantiles]``。``None`` 表示用 top_k 模式。
    n_quantiles:
        quantile 模式的分层数(默认 5 = quintile);仅 ``quantile`` 非 None 时生效。

    Notes
    -----
    * top_k 模式:``weights[t]`` = 对 ``因子[t]`` 横截面 ``rank(ascending=False,
      method="first")`` 前 ``top_k`` 的资产等权 ``1/k``(``k = min(top_k, 当日
      可用资产数)``)。窗口不足的行(因子全 NaN)→ 全现金。
    * quantile 模式:对 ``因子[t]`` 调 FRA-51 ``quantile_bucket(n_quantiles)``,
      做多 ``quantile`` 层(等权)。NaN 因子 / 窗口不足 → 全现金。
    * 选股方向:默认做多因子值最大的资产(momentum 高 = 强)。``volatility`` 维度
      即「高波动组合」的敏感性研究(合法研究维度)。
    """

    def __init__(
        self,
        factor: FactorName = "momentum",
        window: int = 63,
        *,
        top_k: int = 1,
        quantile: int | None = None,
        n_quantiles: int = 5,
    ) -> None:
        if factor not in _FACTOR_NAMES:
            raise ValueError(f"factor must be one of {_FACTOR_NAMES}, got {factor!r}")
        if window <= 0:
            raise ValueError(f"window must be positive (got {window})")
        if quantile is None:
            if top_k <= 0:
                raise ValueError(f"top_k must be positive (got {top_k})")
        else:
            if n_quantiles < 1:
                raise ValueError(f"n_quantiles must be >= 1 (got {n_quantiles})")
            if not (1 <= quantile <= n_quantiles):
                raise ValueError(
                    f"quantile must be within [1, n_quantiles={n_quantiles}] (got {quantile})"
                )
        self._factor = factor
        self._window = window
        self._top_k = top_k
        self._quantile = quantile
        self._n_quantiles = n_quantiles

    def weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        factor_values = self._compute_factor(prices)
        selected = self._select(factor_values)
        counts = selected.sum(axis=1)
        # 空选日(窗口不足 / 全 NaN)→ count=0 → NaN 屏蔽 → fillna(0) 全现金。
        weights = selected.astype("float64").div(counts.replace(0, np.nan), axis=0).fillna(0.0)
        weights.columns = [str(c) for c in prices.columns]
        return weights

    def _compute_factor(self, prices: pd.DataFrame) -> pd.DataFrame:
        if self._factor == "momentum":
            return momentum(prices, self._window)
        if self._factor == "rsi":
            return rsi(prices, period=self._window)
        return volatility(prices, window=self._window)

    def _select(self, factor_values: pd.DataFrame) -> pd.DataFrame:
        if self._quantile is not None:
            # quantile 层:1 = 最低因子值,N = 最高;选指定层等权做多。
            buckets = quantile_bucket(factor_values, n_quantiles=self._n_quantiles)
            return buckets.eq(self._quantile)
        # top_k:rank 1 = 最大因子值(做多候选);method="first" 确定性破平。
        ranks = factor_values.rank(axis=1, ascending=False, method="first")
        return ranks.le(self._top_k)
