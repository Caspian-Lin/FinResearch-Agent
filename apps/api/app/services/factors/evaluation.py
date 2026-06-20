"""Factor evaluation — information coefficient (IC) + significance (FRA-52).

IC is the cross-sectional Spearman rank correlation between
``rank(factor_t)`` and ``rank(forward_return_{t→t+h})`` over each decision
date, aggregated into an ``ICResult`` (per-date series + ``ICSummary``).

ANTI-CHEAT (look-ahead): ``forward_returns`` are *future* returns used for
**evaluation only** — they feed statistics, never a ``t``-day strategy
decision. The caller derives them from prices via ``forward_returns``
(``prices.pct_change(horizon).shift(-horizon)``); IC measures a factor's
predictive power, it is not a signal the backtest engine consumes. See
``docs/backtesting-methodology.md`` §Sensitivity and §接口契约.

Pure pandas/numpy — no scipy dependency (FRA-52 acceptance: "no new heavy
dependency"). Spearman is computed as the Pearson correlation of per-row
ranks; the p-value uses the normal approximation (``erfc``), the standard
treatment for IC significance testing. ``scipy`` is used only in tests
(optional) to assert per-row IC aligns with ``scipy.stats.spearmanr``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.services.factors.types import ICResult, ICSummary


def forward_returns(prices: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Forward (future) ``horizon``-day return aligned to each decision date.

    ``result[t] = (price[t+h] - price[t]) / price[t]`` — the return realized
    *after* the ``t`` decision point over the next ``horizon`` bars. The last
    ``horizon`` rows are NaN (no future data available).

    Evaluation-only: never feed this to a ``t``-day strategy decision — doing
    so would leak the future into the present (look-ahead bias).
    """
    if horizon <= 0:
        raise ValueError(f"horizon must be positive, got {horizon}")
    return prices.pct_change(horizon).shift(-horizon)


def _spearman_per_row(factor: pd.DataFrame, forward: pd.DataFrame) -> pd.Series:
    """Per-row (per decision date) Spearman rank correlation.

    Spearman = Pearson correlation of within-row ranks. Each row ranks the
    cross-section independently (``rank(axis=1)``), then the Pearson
    correlation of the two rank vectors is the rank IC for that date. Rows
    with fewer than two jointly-non-NaN assets, or zero variance, yield NaN
    (NaNs excluded pairwise per row; they never leak across dates).
    """
    ranked_factor = factor.rank(axis=1, method="average")
    ranked_forward = forward.rank(axis=1, method="average")
    common = ranked_factor.columns.intersection(ranked_forward.columns)
    fa = ranked_factor.loc[:, common].to_numpy(dtype="float64")
    ra = ranked_forward.loc[:, common].to_numpy(dtype="float64")

    n_rows = fa.shape[0]
    out = np.empty(n_rows, dtype="float64")
    for i in range(n_rows):
        x = fa[i]
        y = ra[i]
        valid = ~(np.isnan(x) | np.isnan(y))
        xv = x[valid]
        yv = y[valid]
        if xv.size < 2:
            out[i] = np.nan
            continue
        xc = xv - xv.mean()
        yc = yv - yv.mean()
        denom = math.sqrt(float(xc @ xc) * float(yc @ yc))
        out[i] = (float(xc @ yc) / denom) if denom != 0.0 else np.nan
    return pd.Series(out, index=factor.index, dtype="float64")


def ic_series(factor: pd.DataFrame, forward_returns: pd.DataFrame) -> pd.Series:
    """Per-decision-date IC series (cross-sectional Spearman rank correlation).

    Indexed by decision date (UTC midnight), aligned to ``factor.index``.
    """
    return _spearman_per_row(factor, forward_returns)


def _normal_two_tailed_p(z: float) -> float:
    """Two-tailed p-value under the standard normal: ``P(|Z| > |z|) = erfc(|z|/√2)``."""
    return math.erfc(abs(z) / math.sqrt(2.0))


def summarize_ic(series: pd.Series) -> ICSummary:
    """Aggregate an IC series into :class:`ICSummary` statistics.

    * ``mean`` / ``std`` — over non-NaN ICs (sample std, ``ddof=1``);
    * ``icir`` — information ratio ``mean / std``;
    * ``t_stat`` — ``√N · mean / std`` (IC significance);
    * ``p_value`` — two-tailed normal approximation of ``t_stat``;
    * ``n`` — number of valid (non-NaN) IC observations;
    * ``positive_rate`` — fraction of valid ICs strictly greater than zero.

    Returns an all-NaN summary (``n=0``) when no valid IC is observed.
    """
    clean = series.dropna()
    n = int(clean.size)
    if n == 0:
        return ICSummary(
            mean=float("nan"),
            icir=float("nan"),
            t_stat=float("nan"),
            p_value=float("nan"),
            n=0,
            positive_rate=float("nan"),
        )
    mean = float(clean.mean())
    std = float(clean.std(ddof=1))
    positive_rate = float((clean > 0).mean())
    # IC values live in [-1, 1]; a std below 1e-12 means the series is
    # effectively constant (floating-point dust, not real dispersion) → ICIR
    # and t-stat are undefined.
    if n > 1 and std > 1e-12:
        icir = mean / std
        t_stat = math.sqrt(n) * mean / std
        p_value = _normal_two_tailed_p(t_stat)
    else:
        icir = float("nan")
        t_stat = float("nan")
        p_value = float("nan")
    return ICSummary(
        mean=mean,
        icir=icir,
        t_stat=t_stat,
        p_value=p_value,
        n=n,
        positive_rate=positive_rate,
    )


@dataclass(frozen=True, slots=True)
class RankIC:
    """Rank information-coefficient evaluator (FRA-52).

    Satisfies :class:`app.services.factors.protocols.InformationCoefficient`.
    Stateless; ``evaluate`` is a thin wrapper over :func:`ic_series` +
    :func:`summarize_ic`.
    """

    def evaluate(
        self,
        factor: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> ICResult:
        """Return the per-date IC series and its summary."""
        series = ic_series(factor, forward_returns)
        return ICResult(series=series, summary=summarize_ic(series))


def evaluate_ic(
    factor: pd.DataFrame,
    forward_returns: pd.DataFrame,
) -> ICResult:
    """Convenience: IC series + summary for ``factor`` vs ``forward_returns``."""
    return RankIC().evaluate(factor, forward_returns)
