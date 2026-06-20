"""Momentum / reversal factor computation (FRA-49, §14 Week 3).

Extracts the ``pct_change(lookback)`` signal that Week-2's
``MomentumStrategy`` (FRA-31) inlined into ``weights`` into a standalone,
reusable, pure factor function. The output wide-frame is what downstream
layers (IC evaluation, quantile backtest, persistence to ``factor_values``)
consume; ``factor_name`` encodes the window (e.g. ``momentum_21``) so it
aligns with the ``factor_values`` composite primary key without a separate
params column.

Numerical口径 deliberately matches ``MomentumStrategy.weights``:
``prices.pct_change(lookback)`` — same pandas primitive, same dtype, same
NaN-on-warmup behaviour. Anti-cheat (look-ahead safety) is structural in
``pct_change``: row ``t`` reads only ``price[t]`` and ``price[t - lookback]``,
both at-or-before ``t``. So a factor reading at ``t`` is fully determined by
data visible at the ``t`` decision point; mutating rows ``> t`` cannot move
it (verified by ``test_factor_value_is_stable_against_future_prices``).

Price wide-frame convention (inherited from the Week-1/2 engine):
index = tz-aware UTC midnight, ascending; columns = ``asset_id``; dtype
``float64``; missing values NaN, **not** forward-filled.
"""

from __future__ import annotations

import pandas as pd

__all__ = [
    "momentum",
    "momentum_21",
    "momentum_63",
    "momentum_126",
    "reversal",
    "reversal_5",
    "reversal_21",
]


def momentum(prices: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Cumulative return over the trailing ``lookback`` sessions (momentum).

    Computes ``prices.pct_change(lookback)`` and returns a wide-frame with the
    same index / columns / dtype as ``prices``. The first ``lookback`` rows are
    NaN (warmup — not enough history yet); rows where the lag-``lookback``
    price is NaN also stay NaN (``pct_change`` propagates missing inputs rather
    than forward-filling, matching the engine's no-fill convention).

    Parameters
    ----------
    prices:
        Price wide-frame (index = UTC midnight, columns = asset_id, float64).
    lookback:
        Trailing window length in rows (trading days). Must be positive;
        ``21`` ≈ 1M, ``63`` ≈ 3M, ``126`` ≈ 6M.

    Returns
    -------
    pd.DataFrame
        Factor-value wide-frame — same shape as ``prices``; cell at ``(t, a)``
        is ``price[t, a] / price[t - lookback, a] - 1``.

    Raises
    ------
    ValueError
        If ``lookback`` is not a positive integer.

    Notes
    -----
    Look-ahead safe by construction: ``pct_change`` only joins row ``t`` to row
    ``t - lookback`` (both ``≤ t``), so the factor reading at ``t`` is
    computable from information available at the ``t`` decision point. The
    value at ``t`` is invariant under any change to rows ``> t``.
    """
    if lookback <= 0:
        raise ValueError(f"lookback must be positive (got {lookback})")
    return prices.pct_change(lookback)


def reversal(prices: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Short-term reversal factor: the negative of momentum.

    Reversal bets that recent winners (losers) will mean-revert, so it is the
    sign-flipped momentum reading: ``-momentum(prices, lookback)``. Same shape,
    index, columns, and NaN-on-warmup behaviour as ``momentum``; only the sign
    differs. Typical horizons are short (e.g. ``lookback=5`` / ``21``) where
    mean-reversion is empirically stronger than continuation.

    Parameters
    ----------
    prices:
        Price wide-frame (index = UTC midnight, columns = asset_id, float64).
    lookback:
        Trailing window length in rows (trading days). Must be positive.

    Returns
    -------
    pd.DataFrame
        Factor-value wide-frame equal to ``-momentum(prices, lookback)``.

    Raises
    ------
    ValueError
        If ``lookback`` is not a positive integer (re-raised from ``momentum``).
    """
    return -momentum(prices, lookback)


# ---------------------------------------------------------------------------
# Convenience constants for the §14 Week-3 canonical horizons (≈ 1M / 3M / 6M
# trading-day cumulative returns) and short-horizon reversals. These wrap the
# generic ``momentum`` / ``reversal`` so callers and downstream ``factor_name``
# keys (``momentum_21`` etc.) share a single source of truth for the window.
# ---------------------------------------------------------------------------


def momentum_21(prices: pd.DataFrame) -> pd.DataFrame:
    """1-month momentum ≈ ``momentum(prices, 21)`` (``factor_name="momentum_21"``)."""
    return momentum(prices, 21)


def momentum_63(prices: pd.DataFrame) -> pd.DataFrame:
    """3-month momentum ≈ ``momentum(prices, 63)`` (``factor_name="momentum_63"``)."""
    return momentum(prices, 63)


def momentum_126(prices: pd.DataFrame) -> pd.DataFrame:
    """6-month momentum ≈ ``momentum(prices, 126)`` (``factor_name="momentum_126"``)."""
    return momentum(prices, 126)


def reversal_5(prices: pd.DataFrame) -> pd.DataFrame:
    """1-week reversal ≈ ``reversal(prices, 5)`` (``factor_name="reversal_5"``)."""
    return reversal(prices, 5)


def reversal_21(prices: pd.DataFrame) -> pd.DataFrame:
    """1-month reversal ≈ ``reversal(prices, 21)`` (``factor_name="reversal_21"``)."""
    return reversal(prices, 21)
