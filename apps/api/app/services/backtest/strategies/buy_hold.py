"""Buy & Hold baseline strategy (FRA-29).

首日按初始权重建仓并持有到期,不再主动调仓。在 FRA-28 引擎的 target-weight
模型下,这意味着 ``weights`` 返回**恒定**目标权重(所有交易日同一行)——引擎
据此把持仓固定在初始权重 → 换手仅发生在首日建仓一次(其余日 ``|Δholdings|=0``),
与"买入持有、不交易"一致。

单资产全仓时,组合收益精确等于该资产累计收益(cumprod);多资产恒权重收益
按引擎 target-weight 简化口径结算(不模拟持有期市值漂移的隐式再平衡,见
``docs/backtesting-methodology.md`` §接口契约「已知取舍」)。

防前视:权重只依赖 universe 成员构成(剔除整列全缺的"从未上市"资产),不
依赖任何具体价格数值 → 天然只用当时可见信息;策略**不**自行 ``shift``(引擎
统一负责 ``holdings = decision.shift(1)``,见 FRA-28 反双重滞后契约)。
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


class BuyAndHoldStrategy:
    """Buy & Hold:首日建仓、持有到期、不调仓(恒定目标权重)。

    Parameters
    ----------
    weights:
        初始权重映射 ``{asset_id: weight}``;``None`` 表示对剔除全缺后的
        universe **等权**(默认)。若提供,缺失资产按 0 处理;权重和可 < 1
        (余额始终为现金,引擎不强制满仓)。

    Notes
    -----
    ``weights(prices)`` 对整列全 ``NaN`` 的资产赋 0(视作从未上市、不可投资),
    其余资产按初始权重赋值;每个交易日的目标权重相同(恒定)。
    """

    def __init__(self, weights: Mapping[str, float] | None = None) -> None:
        # 拷贝一份,避免持有调用方可变映射;None → 等权(空映射走等权分支)。
        self._weights: dict[str, float] = dict(weights) if weights is not None else {}

    def weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        cols = [str(c) for c in prices.columns]
        target = pd.DataFrame(0.0, index=prices.index, columns=cols)

        # 剔除整列全 NaN 的资产(从未上市)→ 不参与建仓。
        investable = [c for c in cols if not prices[c].isna().all()]
        if not investable:
            return target  # 全部资产从未上市 → 全现金

        if self._weights:
            for c in investable:
                target[c] = float(self._weights.get(c, 0.0))
        else:
            equal = 1.0 / len(investable)
            for c in investable:
                target[c] = equal
        return target
