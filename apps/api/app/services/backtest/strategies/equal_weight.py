"""Equal Weight baseline strategy (FRA-29).

每个 rebalance 日把"已上市可投资"的 universe 成员重置为等权 ``1/N``。资产
陆续上市时 ``N`` 随之增大 → 目标权重变化 → 引擎据此计入换手,如实反映
universe 扩容的调仓成本。

防前视:权重数值(等权 ``1/N``)不依赖任何价格数值;可投资性判定使用"截至
决策日该资产是否已上市"的布尔(资产存在性不是未来收益信息,不构成
look-ahead)。策略**不**自行 ``shift``;引擎统一 ``holdings = decision.shift(1)``
负责 T+1 执行延迟(见 FRA-28 反双重滞后契约)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class EqualWeightStrategy:
    """Equal Weight:每个 rebalance 日对可投资 universe 等权配置。

    ``weights(prices)`` 返回每行的目标权重:对"截至当日该列至少有一个有效
    价格"(= 已上市)的资产赋 ``1 / N``(``N`` = 当日已上市资产数),其余资产
    (尚未上市 / 整列全缺)赋 0。整列全 ``NaN`` 的资产恒为 0(剔除)。

    固定 universe(所有资产首日即上市)时目标权重恒为等权,与 Buy & Hold 等权
    在引擎 target-weight 模型下行为一致;区别在动态 universe——Equal Weight 随
    上市扩容重新等权并产生换手,Buy & Hold 维持初始权重不变。
    """

    def weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        # 已上市 = 截至当前行该列累计出现过有效价格(cumsum > 0,含当前行)。
        # 资产"是否上市"是布尔存在性、非收益信息 → 用到当前行不构成 look-ahead。
        ever_listed = prices.notna().cumsum(axis=0) > 0
        # 每行已上市资产数;0(全现金)用 NaN 屏蔽,div 后 fillna 回 0。
        counts = ever_listed.sum(axis=1)
        safe_counts = counts.where(counts > 0, other=np.nan)
        target = ever_listed.astype("float64").div(safe_counts, axis=0).fillna(0.0)
        target.columns = [str(c) for c in prices.columns]
        return target
