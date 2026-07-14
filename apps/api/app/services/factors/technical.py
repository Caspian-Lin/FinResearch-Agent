"""Technical-indicator factors — RSI / MACD / volatility (FRA-50, §14 Week 3).

Pure, side-effect-free factor functions operating on the Week-1/2 price
wide-frame (index = tz-aware UTC midnight ascending; columns = asset_id;
float64; NaN gaps, no ffill). Every output is a wide-frame of the **same
shape and index/columns** as the input, with NaN during the warmup period.

``factor_name`` encodes the factor *and* its parameters (e.g. ``rsi_14``,
``macd_hist``, ``volatility_20d``) so the natural primary key
``(asset_id, factor_name, time, source)`` stays unique downstream (FRA-48).

ANTI-CHEAT (look-ahead safety)
------------------------------
All indicators use only data at ``t`` and earlier:

* RSI uses ``diff`` (local) + Wilder ``ewm(alpha=1/period, adjust=False)`` —
  an exponentially weighted mean whose value at ``t`` is a recursive function
  of gains/losses *up to and including* ``t`` (``ewm`` never reads future
  rows, ``adjust=False`` matches the classic Wilder recurrence seeded from
  the first-period simple mean).
* MACD uses ``ewm`` on prices with the same look-back-only semantics.
* Volatility uses ``rolling(window).std()`` — a trailing window only.

Changing any price at ``t+1`` or later therefore leaves every factor value at
``t`` unchanged (asserted by the look-ahead test). Warmup rows where the
window has insufficient data are NaN — never a silently forward-filled or
future value.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "MacdResult",
    "macd",
    "macd_hist",
    "rsi",
    "rsi_14",
    "volatility",
    "volatility_20d",
    "volatility_63d",
]

# 252 trading days per year — the standard annualisation factor for daily data.
_TRADING_DAYS_PER_YEAR = 252


def rsi(prices: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Relative Strength Index (Wilder smoothing), per-asset, value range [0, 100].

    Implements the classic Wilder RSI: average gains and average losses are
    smoothed with an exponentially weighted mean whose decay is ``alpha =
    1/period`` (equivalent to the textbook "prev_avg * (period-1)/period +
    today/period" recurrence). ``adjust=False`` makes the first smoothed
    value the simple mean of the first ``period`` deltas, matching Wilder's
    seeding. RS = avg_gain / avg_loss; RSI = 100 - 100/(1+RS). Pure-loss
    sequences yield RSI → 0, pure-gain → 100.

    Parameters
    ----------
    prices:
        Price wide-frame (UTC-midnight index, asset_id columns).
    period:
        Wilder smoothing window (default 14). Must be a positive integer.

    Returns
    -------
    pd.DataFrame
        Same shape as ``prices``; factor values in [0, 100] where defined,
        NaN during the ``period``-row warmup and on constant-price spans
        (avg_loss == 0 → RSI defined as 100; both averages 0 → NaN).

    Notes
    -----
    Look-ahead safe: ``diff`` and ``ewm(alpha=1/period, adjust=False)`` read
    only rows at ``t`` and earlier. The first ``period`` rows are NaN (no
    smoothed average yet). Above 70 is conventionally "overbought", below 30
    "oversold".
    """
    if period <= 0:
        raise ValueError(f"period must be positive (got {period})")

    delta = prices.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    # Wilder smoothing == EWMA with alpha = 1/period, non-adjusted (recursive,
    # seeded from the simple mean of the first `period` observations).
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss
    # avg_loss == 0 (all gains) → RSI 100; both averages 0 (flat) → NaN.
    rsi_vals = 100.0 - (100.0 / (1.0 + rs))
    # Where avg_loss is 0 and avg_gain > 0 → pure-gain → 100.
    pure_gain = (avg_loss == 0.0) & (avg_gain > 0.0)
    rsi_vals = rsi_vals.where(~pure_gain, 100.0)
    # Where both averages are 0 (flat prices) → undefined → NaN.
    flat = (avg_gain == 0.0) & (avg_loss == 0.0)
    rsi_vals = rsi_vals.where(~flat, np.nan)

    rsi_vals.columns = [str(c) for c in prices.columns]
    return rsi_vals.astype("float64")


def rsi_14(prices: pd.DataFrame) -> pd.DataFrame:
    """Convenience alias for ``rsi(prices, period=14)`` (the canonical RSI window)."""
    return rsi(prices, period=14)


@dataclass(frozen=True, slots=True)
class MacdResult:
    """Output of :func:`macd`: three same-shape wide-frames.

    ``line`` is the MACD line (fast EMA − slow EMA), ``signal`` the signal
    line (EMA of ``line``), ``hist`` the histogram (``line − signal``). All
    three share the input's index and columns; NaN during warmup.
    """

    line: pd.DataFrame
    signal: pd.DataFrame
    hist: pd.DataFrame


def macd(
    prices: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> MacdResult:
    """Moving Average Convergence Divergence (line / signal / histogram).

    ``line = EMA_fast - EMA_slow`` (exponentially weighted with spans ``fast``
    and ``slow``, ``adjust=False``), ``signal = EMA(line, span=signal)``,
    ``hist = line - signal``. The classic golden cross (``line`` crosses
    above ``signal``) and death cross (below) are readable from ``hist``
    changing sign.

    Parameters
    ----------
    prices:
        Price wide-frame.
    fast:
        Fast EMA span (default 12). Must satisfy ``0 < fast < slow``.
    slow:
        Slow EMA span (default 26). Must satisfy ``slow > fast``.
    signal:
        Signal EMA span (default 9). Must be positive.

    Returns
    -------
    MacdResult
        Frozen record of three same-shape frames (``line``, ``signal``,
        ``hist``), each NaN during the respective warmup.

    Notes
    -----
    Look-ahead safe: ``ewm(span, adjust=False)`` is a recursive filter over
    rows at ``t`` and earlier. Spans (not alphas) are used to match the
    canonical MACD convention.
    """
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError(
            f"fast/slow/signal must be positive (got fast={fast}, slow={slow}, signal={signal})",
        )
    if fast >= slow:
        raise ValueError(f"fast must be strictly less than slow (got fast={fast}, slow={slow})")

    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    signal_line = line.ewm(span=signal, adjust=False).mean()
    hist = line - signal_line

    cols = [str(c) for c in prices.columns]
    for frame in (line, signal_line, hist):
        frame.columns = cols

    return MacdResult(line=line, signal=signal_line, hist=hist)


def macd_hist(
    prices: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD histogram as a standalone factor (``line - signal``), same shape as input.

    Convenience wrapper over :func:`macd` returning only ``hist`` so it can be
    written to ``factor_values`` like any other single-column-per-asset factor.
    Positive → bullish momentum (line above signal), negative → bearish.
    """
    return macd(prices, fast=fast, slow=slow, signal=signal).hist.astype("float64")


def volatility(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    """Annualised realised volatility of daily returns over a trailing window.

    ``volatility = prices.pct_change().rolling(window).std() * sqrt(252)``.
    Uses daily simple returns and a trailing (look-back only) rolling std,
    annualised by :math:`\\sqrt{252}`. ``window`` rows of warmup produce NaN.

    Parameters
    ----------
    prices:
        Price wide-frame.
    window:
        Rolling window in trading days. Must be a positive integer ``>= 2``
        (a 1-day window has undefined std).

    Returns
    -------
    pd.DataFrame
        Annualised volatility, same shape as ``prices``; NaN during warmup.

    Notes
    -----
    Look-ahead safe: ``pct_change`` is local, ``rolling(window).std()`` uses
    only the trailing ``window`` returns at and before ``t``.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2 (got {window})")

    rets = prices.pct_change()
    vol = rets.rolling(window).std() * np.sqrt(_TRADING_DAYS_PER_YEAR)
    vol.columns = [str(c) for c in prices.columns]
    return vol.astype("float64")


def volatility_20d(prices: pd.DataFrame) -> pd.DataFrame:
    """Convenience alias for ~1-month realised volatility (``window=20``)."""
    return volatility(prices, window=20)


def volatility_63d(prices: pd.DataFrame) -> pd.DataFrame:
    """Convenience alias for ~1-quarter realised volatility (``window=63``)."""
    return volatility(prices, window=63)
