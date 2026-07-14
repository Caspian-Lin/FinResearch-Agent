"""Factor research behaviour protocols — Factor, IC, QuantileBacktester (FRA-47).

Protocols decouple *what* a factor / evaluator / quantile backtester must do
from *how* later Week-3 issues implement it. All are ``runtime_checkable`` so
tests can assert a concrete class satisfies the contract via ``isinstance``
once implementations land.

Anti-cheat semantics (look-ahead safety) are encoded in each docstring and
mirror ``docs/backtesting-methodology.md`` §接口契约.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

from app.services.factors.types import ICResult, QuantileResult


@runtime_checkable
class Factor(Protocol):
    """Compute a factor value wide-frame from a price wide-frame.

    ``compute`` receives the price wide-frame (index = UTC midnight, columns =
    asset_id; the same convention as the backtest engine, see
    ``app/services/backtest/types.py``) and returns a same-index frame whose
    cells are the factor reading for that asset on that decision date.

    ANTI-CHEAT (look-ahead): implementations may use only rows at ``t`` and
    earlier (rolling / expanding windows only). A factor value at ``t`` must be
    knowable using solely information visible at the ``t`` decision point;
    never index ``t+1`` or later. Concrete momentum / technical-indicator
    factors are delivered by FRA-49 / FRA-50.
    """

    def compute(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Return factor values aligned to ``prices`` (index = UTC midnight)."""
        ...


@runtime_checkable
class InformationCoefficient(Protocol):
    """Evaluate a factor's predictive power via information coefficient.

    IC is the cross-sectional Spearman rank correlation between
    ``rank(factor_t)`` and ``rank(forward_return_{t→t+h})`` over each decision
    date, aggregated into an ``ICResult`` (per-date series + ``ICSummary``).

    ANTI-CHEAT: ``forward_returns`` are *future* returns used for evaluation
    only — the caller derives them from prices (e.g.
    ``prices.pct_change(horizon).shift(-horizon)``). They feed statistics,
    never a ``t``-day strategy decision. Implemented by FRA-52.
    """

    def evaluate(
        self,
        factor: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> ICResult:
        """Return the IC series and summary for ``factor`` vs ``forward_returns``."""
        ...


@runtime_checkable
class QuantileBacktester(Protocol):
    """Run a stratified (quantile) backtest over a factor.

    Splits the universe into ``n_quantiles`` buckets per decision date by
    factor value (1 = lowest, N = highest), holds each bucket equal-weight,
    and returns per-bucket equity, the long-top / short-bottom spread, and a
    monotonicity score.

    ANTI-CHEAT: rebuckets on the ``t`` factor value but holds from ``t+1``
    onward, reusing the engine's ``holdings = decision.shift(1)`` boundary
    (FRA-28) so a ``t``-day signal never moves the ``t``-day return.
    Implemented by FRA-53.
    """

    def run(
        self,
        factor: pd.DataFrame,
        prices: pd.DataFrame,
        n_quantiles: int,
    ) -> QuantileResult:
        """Return per-quantile equity, top-minus-bottom, and monotonicity."""
        ...
