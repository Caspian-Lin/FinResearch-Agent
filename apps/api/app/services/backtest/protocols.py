"""Backtest behaviour protocols — Strategy and BacktestEngine (FRA-25).

Protocols decouple *what* a strategy/engine must do from *how* later issues
implement it. Both are ``runtime_checkable`` so tests can assert a concrete
class satisfies the contract via ``isinstance`` once implementations land.

See ``docs/backtesting-methodology.md`` §接口契约 for the anti-cheat
semantics encoded below.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

from app.services.backtest.types import BacktestConfig, BacktestResult


@runtime_checkable
class Strategy(Protocol):
    """Target-portfolio-weight policy.

    ``weights`` receives a price wide-frame (index = UTC midnight, columns =
    asset_id) and must return a same-shaped target-weight frame. Each output
    row is the target portfolio for the *next* rebalance; row sums should lie
    in ``[0, 1]`` (cash holds the remainder, ``1 - sum``).

    ANTI-CHEAT (look-ahead): implementations may use only rows at ``t-1`` and
    earlier. The engine enforces this by feeding ``prices.shift(1)`` to the
    decision point; a strategy must never index future rows. Baseline weight
    math (equal-weight, MA crossover, momentum, ...) is delivered by the
    per-strategy issues, not here.
    """

    def weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Return target weights aligned to ``prices`` (each row sums to ≤ 1)."""
        ...


@runtime_checkable
class BacktestEngine(Protocol):
    """Vectorized daily backtest runner.

    ``run`` applies ``config.rebalance``-frequency target weights to ``prices``
    and returns the full result. Implementation — the ``run`` loop, return
    settlement, transaction-cost deduction, turnover bookkeeping — is delivered
    by the engine-core issue; this signature lets strategies, metrics, and the
    API code against a stable contract before that lands.
    """

    def run(self, config: BacktestConfig, prices: pd.DataFrame) -> BacktestResult:
        """Execute the backtest; return equity, returns, turnover, positions, metrics."""
        ...
