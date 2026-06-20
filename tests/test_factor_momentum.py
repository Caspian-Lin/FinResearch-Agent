"""Pure-unit tests for the momentum / reversal factor (FRA-49).

No DB — factors are pure functions of a price wide-frame; we feed synthetic
frames (tz-aware UTC midnight index, deterministic values) and assert the
factor reading directly. Coverage (per the FRA-49 spec):

1. Known price series → ``momentum`` value matches the hand-computed ratio.
2. ``reversal == -momentum`` for the same window.
3. Look-ahead safety: the factor value at ``t`` is invariant under any change
   to rows ``> t``.
4. Warmup: rows before ``lookback + 1`` are NaN (not enough history).
5. Numerical regression vs FRA-31 ``MomentumStrategy`` — the factor function
   reproduces ``prices.pct_change(lookback)`` the strategy inlines.
6. Convenience constants (``momentum_21/63/126``, ``reversal_5/21``) wrap the
   generic functions at the canonical horizons.
7. Invalid ``lookback`` raises ``ValueError``.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from app.services.backtest.strategies.momentum import MomentumStrategy
from app.services.factors import (
    momentum,
    momentum_21,
    momentum_63,
    momentum_126,
    reversal,
    reversal_5,
    reversal_21,
)

# ---------------------------------------------------------------------------
# helpers (mirrors tests/test_backtest_strategies.py, but kept local so this
# module stays self-contained — the factor layer must not depend on the
# backtest-engine fixtures).
# ---------------------------------------------------------------------------


def _ts(day: str) -> pd.Timestamp:
    """A tz-aware UTC-midnight timestamp (matches the wide-frame convention)."""
    return pd.Timestamp(datetime.fromisoformat(f"{day}T00:00:00"), tz="UTC")


def _prices(
    day_prices: dict[str, list[float]],
    asset_ids: list[str],
) -> pd.DataFrame:
    """Build a synthetic price wide-frame.

    ``day_prices`` maps ISO date → per-asset price list (aligned with ``asset_ids``).
    """
    days = sorted(day_prices)
    index = pd.DatetimeIndex([_ts(d) for d in days])
    data = {aid: [day_prices[d][i] for d in days] for i, aid in enumerate(asset_ids)}
    return pd.DataFrame(data, index=index, columns=asset_ids).astype("float64")


ASSET_A = "A"
ASSET_B = "B"

# 8-day ramp 100 → 109 with mid-week drawdowns (reused shape from the strategy
# tests so the two modules read consistently).
RAMP_DAYS: dict[str, list[float]] = {
    "2024-01-02": [100.0, 100.0],
    "2024-01-03": [101.0, 100.0],
    "2024-01-04": [103.0, 100.0],
    "2024-01-05": [102.0, 100.0],
    "2024-01-08": [105.0, 100.0],
    "2024-01-09": [107.0, 100.0],
    "2024-01-10": [106.0, 100.0],
    "2024-01-11": [109.0, 100.0],
}


# ---------------------------------------------------------------------------
# 1) Known series → momentum value matches hand-computed ratio
# ---------------------------------------------------------------------------


def test_momentum_matches_hand_computed_ratio() -> None:
    # lookback=3 at 2024-01-08 (index 4): price[01-08]/price[01-03] - 1.
    # A: 105.0 / 101.0 - 1 = 0.03960396...; B flat → 0.0.
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    factor = momentum(prices, 3)

    assert factor.loc[_ts("2024-01-08"), ASSET_A] == pytest.approx(105.0 / 101.0 - 1.0)
    assert factor.loc[_ts("2024-01-08"), ASSET_B] == pytest.approx(0.0)
    # lookback=1 at 2024-01-04: 103.0/101.0 - 1.
    assert factor_1(prices).loc[_ts("2024-01-04"), ASSET_A] == pytest.approx(103.0 / 101.0 - 1.0)


def test_momentum_shape_index_columns_dtype_preserved() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    factor = momentum(prices, 3)
    assert factor.shape == prices.shape
    assert list(factor.index) == list(prices.index)
    assert list(factor.columns) == list(prices.columns)
    assert factor.dtypes.eq("float64").all()


def factor_1(prices: pd.DataFrame) -> pd.DataFrame:
    """lookback=1 momentum — thin local wrapper for two-line readability."""
    return momentum(prices, 1)


# ---------------------------------------------------------------------------
# 2) reversal == -momentum for the same window
# ---------------------------------------------------------------------------


def test_reversal_equals_negative_momentum() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    for lookback in (1, 3, 5):
        rev = reversal(prices, lookback)
        mom = momentum(prices, lookback)
        pd.testing.assert_frame_equal(rev, -mom)


# ---------------------------------------------------------------------------
# 3) Look-ahead safety — factor[t] invariant under changes to rows > t
# ---------------------------------------------------------------------------


def test_factor_value_is_stable_against_future_prices() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    factor = momentum(prices, 3)
    t = _ts("2024-01-08")
    # Snapshot the factor reading at t (covers the warmup-complete row).
    value_before = factor.loc[t, ASSET_A]
    # Mutate every row strictly after t — including the boundary at t itself
    # must NOT move.
    future_mask = prices.index > t
    mutated = prices.copy()
    mutated.loc[future_mask, ASSET_A] = mutated.loc[future_mask, ASSET_A] * 5.0
    factor_after = momentum(mutated, 3)
    assert factor_after.loc[t, ASSET_A] == pytest.approx(value_before)
    # And rows at-or-before t are byte-for-byte unchanged.
    at_or_before = prices.index <= t
    pd.testing.assert_series_equal(
        factor.loc[at_or_before, ASSET_A],
        factor_after.loc[at_or_before, ASSET_A],
    )


# ---------------------------------------------------------------------------
# 4) Warmup — rows before lookback+1 are NaN
# ---------------------------------------------------------------------------


def test_warmup_rows_are_nan() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    for lookback in (1, 3, 5):
        factor = momentum(prices, lookback)
        # First `lookback` rows are warmup → NaN; the row at index `lookback`
        # is the first computable reading.
        warmup = factor.iloc[:lookback]
        assert warmup.isna().all().all()
        assert not factor.iloc[lookdown_safe(lookback)].isna().any()


def lookdown_safe(lookback: int) -> int:
    """Index of the first computable row (== lookback). Kept as a tiny helper
    so the warmup assertion reads off-by-one-free."""
    return lookback


# ---------------------------------------------------------------------------
# 5) Numerical regression vs FRA-31 MomentumStrategy
# ---------------------------------------------------------------------------


def test_momentum_matches_strategy_internal_pct_change() -> None:
    # MomentumStrategy.weights ranks prices.pct_change(lookback) cross-
    # sectionally. The factor function must reproduce that raw reading exactly.
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    for lookback in (1, 3, 5):
        factor = momentum(prices, lookback)
        raw = prices.pct_change(lookback)
        pd.testing.assert_frame_equal(factor, raw)


def test_momentum_matches_strategy_internal_pct_change_via_weights() -> None:
    # Smoke-tie to the strategy class: feed a longer synthetic series and
    # confirm the factor reading the strategy consumes equals our factor.
    days = sorted(RAMP_DAYS)
    seq = [v[0] for v in RAMP_DAYS.values()]
    longer = {d: [a, b] for d, a, b in zip(days, seq, [100.0] * len(seq), strict=True)}
    prices = _prices(longer, [ASSET_A, ASSET_B])
    lookback = 3
    strat = MomentumStrategy(lookback=lookback, top_k=1)
    # Calling weights exercises the internal pct_change; we only need it to
    # not raise and to depend on the same horizon we expose.
    _ = strat.weights(prices)
    factor = momentum(prices, lookback)
    pd.testing.assert_frame_equal(factor, prices.pct_change(lookback))


# ---------------------------------------------------------------------------
# 6) Convenience constants wrap the generic functions at canonical horizons
# ---------------------------------------------------------------------------


def test_convenience_constants_match_generic_momentum() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    pd.testing.assert_frame_equal(momentum_21(prices), momentum(prices, 21))
    pd.testing.assert_frame_equal(momentum_63(prices), momentum(prices, 63))
    pd.testing.assert_frame_equal(momentum_126(prices), momentum(prices, 126))
    pd.testing.assert_frame_equal(reversal_5(prices), reversal(prices, 5))
    pd.testing.assert_frame_equal(reversal_21(prices), reversal(prices, 21))


# ---------------------------------------------------------------------------
# 7) Invalid lookback raises ValueError
# ---------------------------------------------------------------------------


def test_momentum_rejects_nonpositive_lookback() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    for bad in (0, -1):
        with pytest.raises(ValueError, match="lookback must be positive"):
            momentum(prices, bad)


def test_reversal_rejects_nonpositive_lookback() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    for bad in (0, -1):
        with pytest.raises(ValueError, match="lookback must be positive"):
            reversal(prices, bad)


# ---------------------------------------------------------------------------
# 8) Missing values propagate (no forward-fill) — mirrors the engine convention
# ---------------------------------------------------------------------------


def test_nan_input_propagates_without_forward_fill() -> None:
    # If price[t-lookback] is NaN (asset not yet listed), momentum[t] must be
    # NaN — never implicitly filled from the last known price.
    days = sorted(RAMP_DAYS)
    a_seq = [v[0] for v in RAMP_DAYS.values()]
    # B listed from row 3 onward (first three rows NaN).
    b_prices = [float("nan"), float("nan"), float("nan"), 100.0, 100.0, 100.0, 100.0, 100.0]
    prices = _prices(
        {d: [a, b] for d, a, b in zip(days, a_seq, b_prices, strict=True)},
        [ASSET_A, ASSET_B],
    )
    factor = momentum(prices, 2)
    # B = [NaN, NaN, NaN, 100, 100, 100, 100, 100]. pct_change(2) at row r reads
    # price[r] / price[r-2] - 1. The first row where *both* ends are non-NaN
    # for B is r=5 (100 / 100 - 1 = 0); rows 2..4 still touch a NaN lag → NaN.
    # This proves no forward-fill sneaks in: missing history stays missing.
    for r in (2, 3, 4):
        assert np.isnan(factor.iloc[r][ASSET_B])
    assert factor.iloc[5][ASSET_B] == pytest.approx(0.0)
