"""Moving Average Crossover baseline strategy (FRA-30, §11.1).

经典快慢均线穿越择时:``fast`` 上穿 ``slow`` → 做多,下穿 → 空仓。作为技术
分析 baseline,与 Buy & Hold 对照(曲线/指标对比留给后续 issue)。

防前视 / 反双重滞后(重要)
----------------------------
本策略**不**自行 ``shift`` 均线或权重。FRA-28 引擎已统一执行
``holdings = decision.shift(1)``(t 日决策 t+1 执行);若策略层再对均线
``shift(1)``,信号会**双重滞后**(金叉 2 个交易日后才生效,失真)。因此:

* ``weights[t]`` 直接用含 ``t`` 日收盘的均线 ``ma[t]`` 生成信号;
* 引擎在 ``t+1`` 执行 ``holdings[t+1] = weights[t]`` —— ``t`` 日收盘价在
  ``t+1`` 已知 → 无 look-ahead,且只延迟一次。

(FRA-30 issue 文字里的 ``rolling.mean().shift(1)`` 表达的是"均线只用已实现
收盘价"的防前视*意图*;在 FRA-28 engine 已 shift 的前提下,该意图由 engine
的 ``shift(1)`` 兑现,策略层不再额外 shift。)

做空说明:当前 ``Strategy`` 协议约束每行权重之和 ∈ ``[0, 1]``(现金补足),
不支持负权重,故本实现为**多空二态**(金叉 → 做多、死叉 → 空仓),不实现
做空。做空需协议扩展为允许负权重,留待未来。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class MACrossoverStrategy:
    """快慢均线穿越择时:金叉做多、死叉空仓。

    Parameters
    ----------
    fast:
        快均线周期(交易日),必须 ``< slow`` 且为正。
    slow:
        慢均线周期(交易日),必须 ``> fast`` 且为正。

    Notes
    -----
    对每个资产独立计算简单移动平均(SMA);``fast_ma > slow_ma`` 即金叉做多
    信号(1),否则 0。窗口不足(前 ``slow - 1`` 行)时均线为 NaN,比较结果为
    False → 空仓(数据不足不下注)。

    多资产(universe)时,把做多资产**等权**分配(``1 / N_long``,
    ``N_long`` = 当日金叉资产数);全部死叉 → 全现金。单资产时金叉即满仓。
    """

    def __init__(self, fast: int = 5, slow: int = 20) -> None:
        if fast <= 0 or slow <= 0:
            raise ValueError(f"fast/slow must be positive (got fast={fast}, slow={slow})")
        if fast >= slow:
            raise ValueError(f"fast must be strictly less than slow (got fast={fast}, slow={slow})")
        self._fast = fast
        self._slow = slow

    def weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        # 含当前日收盘的 SMA;防前视由 engine holdings=decision.shift(1) 兑现。
        fast_ma = prices.rolling(self._fast).mean()
        slow_ma = prices.rolling(self._slow).mean()

        # 金叉状态:fast > slow → 做多(1);NaN(窗口不足)/死叉 → 0。
        long_signal = (fast_ma > slow_ma).astype("float64").fillna(0.0)

        # 多资产:等权分配给当日做多资产;全死叉行(和=0)保持现金(0)。
        n_long = long_signal.sum(axis=1)
        weights = long_signal.div(n_long.replace(0, np.nan), axis=0).fillna(0.0)
        weights.columns = [str(c) for c in prices.columns]
        return weights
