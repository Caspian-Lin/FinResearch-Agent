"""Momentum baseline strategy (FRA-31, §11.1 + §5 场景 A).

横截面动量:每个决策日按过去 ``lookback`` 期累计收益(动量)对 universe 排序,
做多最强的 ``top_k`` 只(等权)。因子研究 baseline。

防前视 / 反双重滞后(同 FRA-30 口径):策略**不**自行 shift。FRA-28 引擎已统一
执行 ``holdings = decision.shift(1)``(t 决策、t+1 执行);若策略层再 shift 会
双重滞后。故 ``weights[t]`` 用含 t 日收盘的动量(``pct_change(lookback)``),
防前视由 engine 的 ``shift(1)`` 兑现:t 日收盘价在 t+1 执行时已知 → 无
look-ahead,只延迟一次(标准 T+1)。

空头:``Strategy`` 协议约束每行权重和 ∈ ``[0, 1]``,不支持负权重 → 只做多
top_k 等权。issue 的「是否空头(默认只多)」需协议扩展允许负权重,留待未来。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class MomentumStrategy:
    """横截面动量:做多过去 lookback 期收益最高的 top_k 只(等权)。

    Parameters
    ----------
    lookback:
        动量回看周期(交易日);约 21=1M、63=3M、126=6M。必须为正。
    top_k:
        做多的最强资产数;universe 可用资产不足 ``top_k`` 时取可用数。必须为正。

    Notes
    -----
    ``weights[t]`` = 对 ``pct_change(lookback)[t]`` 横截面排名前 ``top_k`` 的资产
    等权 ``1 / k``(``k = min(top_k, 当日可用资产数)``)。前 ``lookback`` 行动量为
    NaN(窗口不足)→ 全现金(数据不足不排名)。排名用 ``method="first"``(动量相同
    时按列顺序破平,确定性可复现)。
    """

    def __init__(self, lookback: int = 63, top_k: int = 1) -> None:
        if lookback <= 0:
            raise ValueError(f"lookback must be positive (got {lookback})")
        if top_k <= 0:
            raise ValueError(f"top_k must be positive (got {top_k})")
        self._lookback = lookback
        self._top_k = top_k

    def weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        # 含 t 日收盘的 lookback 累计收益;防前视由 engine shift 兑现(见模块 docstring)。
        momentum = prices.pct_change(self._lookback)
        # 横截面排名:1 = 最高动量(做多候选);NaN(窗口不足)不参与(na_option="keep")。
        ranks = momentum.rank(axis=1, ascending=False, method="first")
        selected = ranks.le(self._top_k)  # rank <= top_k 入选;NaN rank → False
        counts = selected.sum(axis=1)
        weights = selected.astype("float64").div(counts.replace(0, np.nan), axis=0).fillna(0.0)
        weights.columns = [str(c) for c in prices.columns]
        return weights
