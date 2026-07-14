"""Factor research data contracts — factor values, IC, quantile results (FRA-47).

This module is the single source of truth for the in-memory shapes that flow
between the factor-computation, cross-sectional-ranking, IC-evaluation, and
quantile-backtest layers delivered by later Week-3 issues (FRA-49..54). It is a
typed *stub*: the types are final, but no factor math lives here. Concrete
momentum / technical-indicator / IC / quantile implementations are added by the
per-feature issues.

Contracts mirror ``docs/factor-research-methodology.md`` (FRA-59) and align
with the ``packages/shared`` TypeScript types (``FactorValue`` / ``ICSummary``
/ ``QuantileResult``) so the frontend consumes results without a second
translation layer. See also ``docs/backtesting-methodology.md`` §接口契约 for
the shared price wide-frame convention inherited from the Week-2 engine.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True, slots=True)
class FactorValue:
    """One factor observation for one asset on one decision date.

    Mirrors a row of the ``factor_values`` TimescaleDB hypertable (FRA-48):
    ``factor_name`` encodes the factor *and* its parameters (e.g.
    ``momentum_21``, ``rsi_14``, ``volatility_20d``) so the natural primary key
    ``(asset_id, factor_name, time, source)`` stays unique without a separate
    params dimension. ``params`` records the parameter snapshot for
    reproducibility (§11.3 第 6 条). ``value`` is the factor reading at ``time``
    and, per the anti-cheat contract, is computed from data at ``t`` and
    earlier only.
    """

    asset_id: str
    factor_name: str
    time: pd.Timestamp
    value: float
    params: Mapping[str, Any] = field(default_factory=dict)
    source: str = "computed"


@dataclass(frozen=True, slots=True)
class ICSummary:
    """Aggregate statistics of a factor's information-coefficient series.

    IC (information coefficient) is the cross-sectional Spearman rank
    correlation between ``rank(factor_t)`` and ``rank(forward_return_{t→t+h})``
    (FRA-52). ``mean`` is the average IC across decision dates; ``icir`` the
    information ratio (mean / std); ``t_stat`` / ``p_value`` test whether mean
    IC is significantly different from zero; ``n`` is the number of decision
    dates sampled; ``positive_rate`` the fraction of dates with IC > 0. All
    fields are populated by the IC-evaluation issue, not here.
    """

    mean: float
    icir: float
    t_stat: float
    p_value: float
    n: int
    positive_rate: float


@dataclass(slots=True)
class ICResult:
    """IC evaluation output: the per-date IC series plus its summary.

    ``series`` is indexed by decision date (UTC midnight); ``summary`` is the
    ``ICSummary`` computed over ``series``. The ``InformationCoefficient``
    protocol (``protocols.py``) returns this so callers get both the time view
    and the scalar statistics in one call.
    """

    series: pd.Series
    summary: ICSummary


@dataclass(slots=True)
class QuantileResult:
    """Output of a stratified (quantile) backtest over a factor (FRA-53).

    ``quantile_equity`` columns are the quantile labels ``1..N`` (1 = lowest
    factor value, N = highest); each column is the equal-weight equity of that
    bucket, sharing the UTC-midnight index. ``top_minus_bottom`` is the
    long-top / short-bottom spread series. ``monotonicity`` summarizes whether
    average returns increase with quantile rank (e.g. Spearman corr between
    bucket mean return and bucket ordinal). Persistence (``equity_curve`` rows
    vs. this in-memory frame) is settled by the quantile issue.
    """

    quantile_equity: pd.DataFrame
    top_minus_bottom: pd.Series
    monotonicity: float
