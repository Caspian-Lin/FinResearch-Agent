"""Pure-unit tests for the stratified (quantile) backtest (FRA-53).

No DB — the quantile backtester is a pure function of a factor wide-frame and a
price wide-frame (both tz-aware UTC midnight index, asset_id columns, the
Week-2/3 convention). We feed synthetic frames with deterministic per-asset
daily returns and assert the three QuantileResult outputs. Coverage mirrors the
FRA-53 acceptance:

1. Monotone factor → monotone per-bucket returns; ``monotonicity`` ≈ +1
   (and ≈ −1 for an inversely monotone factor).
2. ``top_minus_bottom`` == long-top − short-bottom (cumulative spread).
3. Look-ahead: rebucket at ``t``, hold from ``t+1`` — changing any future
   factor row leaves equity at or before ``t`` untouched.
4. Equal weight within a bucket.
5. Edge cases: ``n_quantiles < 1`` / empty prices raise; NaN-factor assets are
   excluded from bucketing; protocol conformance; shape / index / first value.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from app.services.factors.protocols import QuantileBacktester as QuantileBacktesterProtocol
from app.services.factors.quantile import QuantileBacktester
from app.services.factors.types import QuantileResult

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ts(day: str) -> pd.Timestamp:
    """A tz-aware UTC-midnight timestamp (matches the wide-frame convention)."""
    return pd.Timestamp(datetime.fromisoformat(f"{day}T00:00:00"), tz="UTC")


def _index(n_days: int) -> pd.DatetimeIndex:
    """A tz-aware UTC-midnight daily index of ``n_days`` rows from 2024-01-01."""
    return pd.date_range("2024-01-01", periods=n_days, freq="D", tz="UTC")


def _prices(
    daily_returns: dict[str, float],
    n_days: int,
    asset_ids: list[str],
) -> pd.DataFrame:
    """Build a price wide-frame where each asset grows at a fixed daily return.

    ``daily_returns[aid]`` is the per-bar return; price starts at 100.0 and
    compounds. Assets absent from ``daily_returns`` stay flat (0 return).
    """
    index = _index(n_days)
    data: dict[str, list[float]] = {}
    for aid in asset_ids:
        r = daily_returns.get(aid, 0.0)
        price = 100.0
        col = [price]
        for _ in range(n_days - 1):
            price *= 1.0 + r
            col.append(price)
        data[aid] = col
    return pd.DataFrame(data, index=index, columns=asset_ids).astype("float64")


def _constant_factor(
    values: dict[str, float],
    n_days: int,
    asset_ids: list[str],
) -> pd.DataFrame:
    """Build a factor wide-frame that is constant across all dates.

    ``values[aid]`` is the (date-invariant) factor reading; assets absent stay
    NaN (no factor reading → excluded from bucketing).
    """
    index = _index(n_days)
    data = {aid: [values.get(aid, np.nan)] * n_days for aid in asset_ids}
    return pd.DataFrame(data, index=index, columns=asset_ids).astype("float64")


ASSETS5 = ["a", "b", "c", "d", "e"]
# Monotone factor: a lowest (bucket 1) → e highest (bucket 5).
MONO_FACTOR: dict[str, float] = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0, "e": 5.0}
# Returns rising with the factor → monotone-positive relation.
MONO_RETURNS: dict[str, float] = {
    "a": 0.01,
    "b": 0.02,
    "c": 0.03,
    "d": 0.04,
    "e": 0.05,
}


# ---------------------------------------------------------------------------
# 1) monotone factor → monotone bucket returns; monotonicity ≈ ±1
# ---------------------------------------------------------------------------


def test_monotone_factor_yields_monotone_returns_and_full_monotonicity() -> None:
    n_days = 10
    factor = _constant_factor(MONO_FACTOR, n_days, ASSETS5)
    prices = _prices(MONO_RETURNS, n_days, ASSETS5)

    result = QuantileBacktester().run(factor, prices, n_quantiles=5)

    # Five assets, five buckets → one asset per bucket; bucket k earns k%.
    # Per-bucket mean daily return must rise monotonically 1%..5%.
    means = [result.quantile_equity[k].pct_change().dropna().mean() for k in range(1, 6)]
    assert all(means[i] < means[i + 1] for i in range(len(means) - 1))
    np.testing.assert_allclose(means, [0.01, 0.02, 0.03, 0.04, 0.05], rtol=1e-9)

    # Highest-factor bucket (5) is the top equity; lowest (1) the bottom.
    last = result.quantile_equity.iloc[-1]
    assert last[5] > last[4] > last[3] > last[2] > last[1]

    assert result.monotonicity == pytest.approx(1.0)


def test_inverse_monotone_factor_yields_negative_monotonicity() -> None:
    # High factor → low return: inversely monotone → monotonicity ≈ −1.
    inverse_returns = {"a": 0.05, "b": 0.04, "c": 0.03, "d": 0.02, "e": 0.01}
    n_days = 10
    factor = _constant_factor(MONO_FACTOR, n_days, ASSETS5)
    prices = _prices(inverse_returns, n_days, ASSETS5)

    result = QuantileBacktester().run(factor, prices, n_quantiles=5)

    assert result.monotonicity == pytest.approx(-1.0)
    # Bucket 1 (lowest factor = a = 5% return) now tops bucket 5.
    last = result.quantile_equity.iloc[-1]
    assert last[1] > last[5]


# ---------------------------------------------------------------------------
# 2) top_minus_bottom == long top − short bottom
# ---------------------------------------------------------------------------


def test_top_minus_bottom_is_long_top_short_bottom_spread() -> None:
    n_days = 10
    factor = _constant_factor(MONO_FACTOR, n_days, ASSETS5)
    prices = _prices(MONO_RETURNS, n_days, ASSETS5)

    result = QuantileBacktester().run(factor, prices, n_quantiles=5)

    # Bucket 5 earns 5%/day (e), bucket 1 earns 1%/day (a) → spread 4%/day,
    # compounded from a base of 1.0 (day 0 is the no-return establishment bar).
    expected = np.power(1.04, np.arange(n_days))
    np.testing.assert_allclose(
        result.top_minus_bottom.to_numpy(),
        expected,
        rtol=1e-9,
    )
    # Also equals the long-top / short-bottom combination derived from the
    # per-bucket daily returns directly.
    top_ret = result.quantile_equity[5].pct_change()
    bottom_ret = result.quantile_equity[1].pct_change()
    reconstructed = (1.0 + (top_ret - bottom_ret).fillna(0.0)).cumprod()
    np.testing.assert_allclose(
        result.top_minus_bottom.to_numpy(),
        reconstructed.to_numpy(),
        rtol=1e-9,
    )


# ---------------------------------------------------------------------------
# 3) look-ahead — future factor rows do not move past equity/holdings
# ---------------------------------------------------------------------------


def test_lookahead_future_factor_does_not_move_past_equity() -> None:
    # v1: factor monotonically a..e every day.
    # v2: identical on days 0,1 then *reversed* (e..a) from day 2 onward.
    n_days = 5
    prices = _prices(MONO_RETURNS, n_days, ASSETS5)
    factor_v1 = _constant_factor(MONO_FACTOR, n_days, ASSETS5)

    reversed_factor = {"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}
    factor_v2 = _constant_factor(MONO_FACTOR, n_days, ASSETS5)
    # Overwrite rows 2..end with the reversed cross-section.
    rev_frame = _constant_factor(reversed_factor, n_days, ASSETS5)
    factor_v2.iloc[2:] = rev_frame.iloc[2:]

    r1 = QuantileBacktester().run(factor_v1, prices, n_quantiles=5)
    r2 = QuantileBacktester().run(factor_v2, prices, n_quantiles=5)

    # holdings[t] = decision[t-1] = factor[t-1]. Equity[t] depends only on
    # factor[0..t-1], so rows 0,1,2 (decided by factor[0],factor[1] — identical
    # in v1/v2) must match exactly. The reversal lives in factor[2..], which
    # first moves holdings[3] → equity[3].
    np.testing.assert_allclose(
        r1.quantile_equity.iloc[:3].to_numpy(),
        r2.quantile_equity.iloc[:3].to_numpy(),
        rtol=1e-12,
    )
    np.testing.assert_allclose(
        r1.top_minus_bottom.iloc[:3].to_numpy(),
        r2.top_minus_bottom.iloc[:3].to_numpy(),
        rtol=1e-12,
    )
    # And rows 3+ DO differ — the reversal reaches holdings from day 3.
    assert not np.allclose(
        r1.quantile_equity.iloc[3:].to_numpy(),
        r2.quantile_equity.iloc[3:].to_numpy(),
    )


# ---------------------------------------------------------------------------
# 4) equal weight within a bucket
# ---------------------------------------------------------------------------


def test_equal_weight_within_single_bucket() -> None:
    # One bucket (n_quantiles=1) holds all three assets equal-weight → portfolio
    # return is the cross-section mean (1%, 2%, 3%) = 2%/day.
    assets = ["a", "b", "c"]
    returns = {"a": 0.01, "b": 0.02, "c": 0.03}
    n_days = 8
    factor = _constant_factor({"a": 1.0, "b": 2.0, "c": 3.0}, n_days, assets)
    prices = _prices(returns, n_days, assets)

    result = QuantileBacktester().run(factor, prices, n_quantiles=1)

    # Single bucket labeled 1; mean daily return ≈ 2%.
    mean_ret = result.quantile_equity[1].pct_change().dropna().mean()
    assert mean_ret == pytest.approx(0.02, rel=1e-9)
    # Compounded from 1.0: equity[t] = 1.02^t.
    np.testing.assert_allclose(
        result.quantile_equity[1].to_numpy(),
        np.power(1.02, np.arange(n_days)),
        rtol=1e-9,
    )


# ---------------------------------------------------------------------------
# 5) edge cases & contract
# ---------------------------------------------------------------------------


def test_rejects_nonpositive_n_quantiles() -> None:
    factor = _constant_factor(MONO_FACTOR, 5, ASSETS5)
    prices = _prices(MONO_RETURNS, 5, ASSETS5)
    with pytest.raises(ValueError):
        QuantileBacktester().run(factor, prices, n_quantiles=0)


def test_rejects_empty_prices() -> None:
    factor = pd.DataFrame(dtype="float64")
    prices = pd.DataFrame(dtype="float64")
    with pytest.raises(ValueError):
        QuantileBacktester().run(factor, prices, n_quantiles=5)


def test_nan_factor_assets_excluded_from_buckets() -> None:
    # 4 assets but d has no factor reading → only a,b,c are bucketed (3 assets
    # into 3 buckets → 1 each). d never contributes to any bucket's return.
    assets = ["a", "b", "c", "d"]
    factor = _constant_factor({"a": 1.0, "b": 2.0, "c": 3.0}, 6, assets)  # d → NaN
    # Give d a return so we can prove it is excluded (it would distort buckets
    # if it leaked in).
    prices = _prices({"a": 0.01, "b": 0.02, "c": 0.03, "d": 0.99}, 6, assets)

    result = QuantileBacktester().run(factor, prices, n_quantiles=3)

    # Bucket means are exactly a/b/c returns — d's 99% never appears.
    means = [result.quantile_equity[k].pct_change().dropna().mean() for k in range(1, 4)]
    np.testing.assert_allclose(means, [0.01, 0.02, 0.03], rtol=1e-9)
    assert result.monotonicity == pytest.approx(1.0)


def test_satisfies_quantile_backtester_protocol() -> None:
    assert isinstance(QuantileBacktester(), QuantileBacktesterProtocol)


def test_result_shape_index_and_first_value() -> None:
    n_days = 7
    factor = _constant_factor(MONO_FACTOR, n_days, ASSETS5)
    prices = _prices(MONO_RETURNS, n_days, ASSETS5)

    result = QuantileBacktester().run(factor, prices, n_quantiles=5)

    assert isinstance(result, QuantileResult)
    # quantile_equity: rows = prices rows, columns = quantile labels 1..N.
    assert result.quantile_equity.shape == (n_days, 5)
    assert list(result.quantile_equity.columns) == [1, 2, 3, 4, 5]
    assert result.quantile_equity.index.equals(prices.index)
    # Every bucket (and the spread) starts at 1.0 (establishment bar, no return).
    assert result.quantile_equity.iloc[0].apply(lambda v: v == pytest.approx(1.0)).all()
    assert result.top_minus_bottom.iloc[0] == pytest.approx(1.0)
    assert result.top_minus_bottom.index.equals(prices.index)
