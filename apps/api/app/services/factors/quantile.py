"""Stratified (quantile) backtest over a factor (FRA-53).

Splits the universe into ``n_quantiles`` equal-weight buckets per decision date
by factor value (1 = lowest, N = highest) and measures whether returns rise
monotonically with the factor — the classic factor→return validation view
(§11 回测评估, ``docs/backtesting-methodology.md``). We **reuse the Week-2
``BacktestEngine`` verbatim** rather than re-implementing the backtest loop:
each quantile bucket is run through :func:`run_backtest` as an equal-weight
bucket strategy, so the engine's single anti-cheat boundary
``holdings = decision.shift(1)`` (FRA-28) applies unchanged — a ``t``-day factor
reading rebuckets at ``t`` but only moves returns from ``t+1`` onward.

Outputs (:class:`QuantileResult`):

* ``quantile_equity`` — per-bucket cumulative net value (columns ``1..N``,
  1 = lowest factor value), normalized to start at ``1.0``
  (``initial_capital=1.0``, ``cost_bps=0`` gross);
* ``top_minus_bottom`` — long-top / short-bottom spread: the cumulative value
  of holding the highest-quantile bucket long and the lowest short
  (``daily_return_top − daily_return_bottom``, accumulated);
* ``monotonicity`` — Spearman correlation between per-bucket mean daily return
  and bucket ordinal ``[1..N]``; ``+1`` means returns rise perfectly
  monotonically with the factor, ``−1`` perfectly inverse, ``0`` no monotone
  relation.

ANTI-CHEAT (look-ahead): rebuckets on the ``t`` factor value but holds from
``t+1`` (engine ``shift(1)``); changing any future factor row leaves all
holdings at or before ``t`` untouched. Bucketing uses the FRA-51
:func:`quantile_bucket`, a pure cross-sectional transform (per-date only).
Persistence (``equity_curve`` with ``series_kind=quantile_1..N`` /
``top_minus_bottom``) is settled by the FRA-55 service layer, not here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.services.backtest.engine import run_backtest
from app.services.backtest.types import (
    BacktestConfig,
    BacktestResult,
    PriceField,
    RebalanceFreq,
)
from app.services.factors.ranking import quantile_bucket
from app.services.factors.types import QuantileResult

__all__ = ["QuantileBacktester"]


@dataclass(frozen=True, slots=True)
class _BucketEqualWeight:
    """Decision-day equal-weight target weights for one quantile bucket.

    Internal :class:`Strategy` consumed by :func:`run_backtest`: on each decision
    date every asset assigned to ``level`` by ``bucket_labels`` gets weight
    ``1 / n_in_bucket``; assets in other buckets (or NaN factor) get 0.
    Empty-bucket dates are all-cash (row sums to 0). This is the *decision-day*
    target; the engine applies ``shift(1)`` so holdings lag by one bar — we never
    shift inside the strategy (FRA-28 反双重滞后契约).
    """

    bucket_labels: pd.DataFrame
    level: int

    def weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        # prices aligns the output shape; bucketing already shares it. ``prices``
        # is accepted to satisfy the Strategy protocol and ignored otherwise.
        _ = prices
        mask = self.bucket_labels.eq(self.level)
        # Per-date bucket size; empty-bucket dates → NaN so div yields 0 not inf.
        count = mask.sum(axis=1).replace(0, np.nan)
        return mask.div(count, axis=0).fillna(0.0)


@dataclass(frozen=True, slots=True)
class QuantileBacktester:
    """Stratified quantile backtester (FRA-53).

    Satisfies :class:`app.services.factors.protocols.QuantileBacktester`.
    Stateless; ``run`` fans each quantile bucket through the Week-2 engine.
    """

    def run(
        self,
        factor: pd.DataFrame,
        prices: pd.DataFrame,
        n_quantiles: int,
    ) -> QuantileResult:
        """Return per-quantile equity, top-minus-bottom, and monotonicity.

        Parameters
        ----------
        factor:
            Factor wide-frame (index = UTC midnight, columns = asset_id).
            Reindexed to ``prices``; assets/rows absent in ``factor`` are
            treated as no factor reading (NaN) on that date.
        prices:
            Price wide-frame (same convention as the backtest engine).
        n_quantiles:
            Number of buckets (>= 1); 5 = quintile, 10 = decile.

        Raises
        ------
        ValueError
            ``n_quantiles < 1`` or ``prices`` has no rows / no columns.
        """
        if n_quantiles < 1:
            raise ValueError(f"n_quantiles must be >= 1, got {n_quantiles}")
        if prices.shape[0] == 0 or prices.shape[1] == 0:
            raise ValueError(
                f"prices must contain at least one asset and one row (got shape={prices.shape})"
            )

        # 对齐 factor 到 prices 的 index/columns(缺资产/缺行视为当日无因子 → NaN)。
        aligned_factor = factor.reindex(index=prices.index, columns=prices.columns)
        buckets = quantile_bucket(aligned_factor, n_quantiles=n_quantiles)

        # 共享配置:gross(cost_bps=0)、归一化初始资金 1.0、日频换仓。
        config = BacktestConfig(
            universe=tuple(str(c) for c in prices.columns),
            start=prices.index[0].date(),
            end=prices.index[-1].date(),
            strategy_name="quantile",
            initial_capital=1.0,
            cost_bps=0.0,
            rebalance=RebalanceFreq.DAILY,
            price_field=PriceField.ADJUSTED,
        )

        # 每层跑一次引擎 —— 复用 run_backtest 的 shift(1) 防前视 + 累积口径,
        # 不重写回测循环(验收第 3 条)。
        levels = range(1, n_quantiles + 1)
        per_level: dict[int, BacktestResult] = {
            level: run_backtest(
                prices,
                _BucketEqualWeight(bucket_labels=buckets, level=level),
                config,
            )
            for level in levels
        }

        # 每层累积净值(列 1..N),共享 prices 的 UTC-midnight index。
        quantile_equity = pd.DataFrame(
            {level: per_level[level].equity_curve for level in levels},
            index=prices.index,
        )

        # 多空:long top(N) − short bottom(1)。两层的 net 日收益相减再累积。
        top_returns = per_level[n_quantiles].daily_returns
        bottom_returns = per_level[1].daily_returns
        long_short_returns = (top_returns - bottom_returns).copy()
        long_short_returns.iloc[0] = 0.0
        top_minus_bottom = (1.0 + long_short_returns).cumprod()
        top_minus_bottom.iloc[0] = 1.0
        top_minus_bottom.name = "top_minus_bottom"

        monotonicity = _spearman_monotonicity(per_level, n_quantiles)

        return QuantileResult(
            quantile_equity=quantile_equity,
            top_minus_bottom=top_minus_bottom,
            monotonicity=monotonicity,
        )


def _spearman_monotonicity(
    per_level: dict[int, BacktestResult],
    n_quantiles: int,
) -> float:
    """Spearman correlation between per-level mean daily return and level ordinal.

    Pure pandas (rank-then-Pearson), no scipy. Returns NaN when fewer than two
    levels exist or all levels share the same mean return (no monotone signal
    to score — a constant series has undefined correlation).
    """
    if n_quantiles < 2:
        return float("nan")
    means = pd.Series(
        {level: float(per_level[level].daily_returns.mean()) for level in range(1, n_quantiles + 1)}
    )
    ordinals = pd.Series(
        np.arange(1, n_quantiles + 1, dtype="float64"),
        index=means.index,
    )
    ranked_means = means.rank()
    # All levels sharing the same mean return (e.g. a perfectly symmetric
    # factor) rank to a constant → correlation is undefined. Guard explicitly
    # so we return NaN rather than tripping numpy's divide-by-zero in corrcoef.
    if ranked_means.nunique() <= 1:
        return float("nan")
    corr = ranked_means.corr(ordinals.rank())
    return float(corr)
