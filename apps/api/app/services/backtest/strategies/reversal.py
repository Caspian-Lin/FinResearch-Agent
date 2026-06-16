"""Reversal baseline strategy (FRA-32, §11.1) — Momentum 的对照组。

参数与 Momentum 对称,但反向选股:每个决策日按过去 ``lookback`` 期累计收益排序,
做多**最低**的 ``bottom_k`` 只(等权)。用于验证动量效应是否稳健——若反转显著
优于动量,说明动量信号可能是噪声(§7.2「每个策略与 baseline 比较」)。

防前视 / 反双重滞后:同 FRA-30 / FRA-31 口径,策略**不**自行 shift,由 engine
``holdings = decision.shift(1)`` 兑现(t 日收盘 t+1 执行 → 无 look-ahead)。

空头:同 Momentum,``Strategy`` 协议 [0, 1] 约束不支持负权重 → 只做多 bottom_k
等权。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class ReversalStrategy:
    """横截面反转:做多过去 lookback 期收益最低的 bottom_k 只(等权)。

    与 :class:`MomentumStrategy` 对称(同 lookback / k),仅排序方向相反——选
    动量最弱而非最强,故称「反转」。同 lookback、同 k 下,两者的选股集合互为
    长短极(动量最高 vs 最低)。

    Parameters
    ----------
    lookback:
        动量回看周期(交易日);约 21=1M、63=3M、126=6M。必须为正。
    bottom_k:
        做多的最弱资产数;universe 不足时取可用数。必须为正。

    Notes
    -----
    实现同 Momentum,仅 ``rank(ascending=True)``(1 = 最低动量)。前 ``lookback``
    行窗口不足 → 全现金。排名用 ``method="first"``(破平确定性可复现)。
    """

    def __init__(self, lookback: int = 63, bottom_k: int = 1) -> None:
        if lookback <= 0:
            raise ValueError(f"lookback must be positive (got {lookback})")
        if bottom_k <= 0:
            raise ValueError(f"bottom_k must be positive (got {bottom_k})")
        self._lookback = lookback
        self._bottom_k = bottom_k

    def weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        momentum = prices.pct_change(self._lookback)
        # 反转:1 = 最低动量(做多候选)。
        ranks = momentum.rank(axis=1, ascending=True, method="first")
        selected = ranks.le(self._bottom_k)
        counts = selected.sum(axis=1)
        weights = selected.astype("float64").div(counts.replace(0, np.nan), axis=0).fillna(0.0)
        weights.columns = [str(c) for c in prices.columns]
        return weights
