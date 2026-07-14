"""Pure-unit tests for the technical factors RSI / MACD / volatility (FRA-50).

No DB — factors are pure functions of a price wide-frame; we feed synthetic
frames (tz-aware UTC midnight index, deterministic values, the same
convention as ``test_backtest_strategies.py``) and assert value-range, sign,
shape, look-ahead safety, and warmup-NaN behaviour. Coverage:

1. RSI value range ∈ [0, 100]; monotone-rising series → RSI → 100,
   monotone-falling → RSI → 0; overbought/oversold 70/30 boundary works.
2. MACD golden/death cross (line crosses above/below signal); hist = line - signal.
3. volatility matches the hand-computed ``pct_change().rolling(window).std()*sqrt(252)``.
4. Look-ahead: changing prices at t+1 onward leaves the factor value at t unchanged.
5. Warmup: insufficient data returns NaN (never a future value).
6. Output shape == input shape; columns stringified; convenience aliases agree.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest
from app.services.factors.technical import (
    MacdResult,
    macd,
    macd_hist,
    rsi,
    rsi_14,
    volatility,
    volatility_20d,
    volatility_63d,
)

# ---------------------------------------------------------------------------
# helpers (mirror tests/test_backtest_strategies.py)
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


def _dates(n: int, start: str = "2024-01-02") -> list[str]:
    """``n`` consecutive calendar dates as ISO strings (good enough for unit tests)."""
    start_ts = datetime.fromisoformat(f"{start}T00:00:00")
    return [(start_ts + pd.Timedelta(days=i)).date().isoformat() for i in range(n)]


ASSET_A = "A"
ASSET_B = "B"


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


def test_rsi_value_range_and_warmup() -> None:
    # 60 days: gentle up-drift so avg_gain dominates but never zero loss.
    n = 60
    days = _dates(n)
    prices_seq = [100.0 * (1.0 + 0.002 * i) + (0.5 if i % 3 == 0 else -0.3) for i in range(n)]
    px = _prices(
        {d: [v, 100.0 - 0.001 * i] for d, i, v in zip(days, range(n), prices_seq, strict=True)},
        [ASSET_A, ASSET_B],
    )

    out = rsi(px, period=14)

    # Shape + columns preserved.
    assert out.shape == px.shape
    assert list(out.columns) == [ASSET_A, ASSET_B]
    assert out.index.equals(px.index)

    # Warmup: first `period` rows are NaN (diff costs 1 row, min_periods=period).
    finite = out[ASSET_A].dropna()
    assert finite.size <= n - 14
    # All finite values within [0, 100].
    assert (finite >= 0.0).all() and (finite <= 100.0).all()


def test_rsi_monotone_rising_approaches_100_falling_approaches_0() -> None:
    n = 60
    days = _dates(n)
    rising = [100.0 + i for i in range(n)]  # pure gain
    falling = [200.0 - i for i in range(n)]  # pure loss
    px = _prices(
        {d: [r, f] for d, r, f in zip(days, rising, falling, strict=True)}, [ASSET_A, ASSET_B]
    )

    out = rsi(px, period=14)

    # Pure-gain series → RSI 100; pure-loss → 0 (in the finite region).
    a_finite = out[ASSET_A].dropna()
    b_finite = out[ASSET_B].dropna()
    assert (a_finite == 100.0).all()
    assert (b_finite == 0.0).all()


def test_rsi_overbought_oversold_boundary() -> None:
    # Construct a strong-then-reversal so RSI first exceeds 70 (overbought),
    # then dips below 30 (oversold) after the reversal.
    n_up = 25
    n_down = 35
    seq = [100.0 * (1.01**i) for i in range(n_up)]
    peak = seq[-1]
    seq += [peak * (0.97 ** (i + 1)) for i in range(n_down)]
    days = _dates(len(seq))
    px = _prices({d: [v] for d, v in zip(days, seq, strict=True)}, [ASSET_A])

    out = rsi(px, period=14)
    finite = out[ASSET_A].dropna()

    # During the run-up RSI should be overbought (>= 70) at least once.
    early = finite.iloc[: n_up - 14]
    assert (early >= 70.0).any()
    # During the drawdown RSI should be oversold (<= 30) at least once.
    late = finite.iloc[n_up - 14 :]
    assert (late <= 30.0).any()


def test_rsi_rejects_bad_period() -> None:
    px = _prices({_dates(20)[0]: [100.0]}, [ASSET_A])
    with pytest.raises(ValueError):
        rsi(px, period=0)


def test_rsi_14_alias_matches_rsi() -> None:
    n = 40
    days = _dates(n)
    seq = [100.0 + np.sin(i / 3.0) * 2.0 + i * 0.1 for i in range(n)]
    px = _prices({d: [v] for d, v in zip(days, seq, strict=True)}, [ASSET_A])
    pd.testing.assert_frame_equal(rsi_14(px), rsi(px, period=14))


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


def test_macd_returns_three_same_shape_frames() -> None:
    n = 60
    days = _dates(n)
    seq = [100.0 + np.sin(i / 4.0) * 3.0 for i in range(n)]
    px = _prices({d: [v, v * 1.1] for d, v in zip(days, seq, strict=True)}, [ASSET_A, ASSET_B])

    result = macd(px)
    assert isinstance(result, MacdResult)
    for frame in (result.line, result.signal, result.hist):
        assert frame.shape == px.shape
        assert list(frame.columns) == [ASSET_A, ASSET_B]
        assert frame.index.equals(px.index)
    # hist is exactly line - signal.
    pd.testing.assert_frame_equal(result.hist, result.line - result.signal)


def test_macd_golden_and_death_cross() -> None:
    # Build a price series with a clear trend reversal so MACD line crosses
    # signal up then down.
    n = 80
    days = _dates(n)
    up = [100.0 * (1.01**i) for i in range(n // 2)]
    peak = up[-1]
    down = [peak * (0.99 ** (i + 1)) for i in range(n - n // 2)]
    seq = up + down
    px = _prices({d: [v] for d, v in zip(days, seq, strict=True)}, [ASSET_A])

    result = macd(px, fast=5, slow=20, signal=5)
    hist = result.hist[ASSET_A].dropna()

    # A golden cross = hist goes from <= 0 to > 0.
    sign = np.sign(hist.values)
    # Drop zeros by treating them as continuation; find a +1 after -1 region.
    has_golden = any(sign[i - 1] <= 0 and sign[i] > 0 for i in range(1, len(sign)))
    # A death cross = hist goes from >= 0 to < 0.
    has_death = any(sign[i - 1] >= 0 and sign[i] < 0 for i in range(1, len(sign)))
    assert has_golden, "expected at least one MACD golden cross"
    assert has_death, "expected at least one MACD death cross"


def test_macd_rejects_bad_params() -> None:
    n = 40
    days = _dates(n)
    seq = [100.0 + i for i in range(n)]
    px = _prices({d: [v] for d, v in zip(days, seq, strict=True)}, [ASSET_A])
    with pytest.raises(ValueError):
        macd(px, fast=0, slow=26, signal=9)
    with pytest.raises(ValueError):
        macd(px, fast=26, slow=26, signal=9)  # fast not strictly < slow
    with pytest.raises(ValueError):
        macd(px, fast=12, slow=26, signal=0)


def test_macd_hist_factor_matches_macd_hist() -> None:
    n = 50
    days = _dates(n)
    seq = [100.0 + np.sin(i / 3.0) * 2.0 for i in range(n)]
    px = _prices({d: [v, v * 0.9] for d, v in zip(days, seq, strict=True)}, [ASSET_A, ASSET_B])
    pd.testing.assert_frame_equal(macd_hist(px), macd(px).hist)


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------


def test_volatility_matches_hand_computation() -> None:
    n = 40
    days = _dates(n)
    rng = np.random.default_rng(42)
    seq = list(100.0 + rng.normal(0.0, 1.5, size=n).cumsum())
    px = _prices({d: [v, 100.0] for d, v in zip(days, seq, strict=True)}, [ASSET_A, ASSET_B])

    window = 10
    expected = px.pct_change().rolling(window).std() * np.sqrt(252)
    out = volatility(px, window=window)
    pd.testing.assert_frame_equal(out, expected.astype("float64"))


def test_volatility_warmup_nan_and_nonneg() -> None:
    n = 30
    days = _dates(n)
    rng = np.random.default_rng(7)
    seq = list(100.0 + rng.normal(0.0, 1.0, size=n).cumsum())
    px = _prices({d: [v] for d, v in zip(days, seq, strict=True)}, [ASSET_A])

    window = 7
    out = volatility(px, window=window)
    # First `window` rows (after the pct_change shift) are NaN.
    assert out[ASSET_A].iloc[:window].isna().all()
    # Finite values are non-negative (std is non-negative).
    finite = out[ASSET_A].dropna()
    assert (finite >= 0.0).all()


def test_volatility_rejects_bad_window() -> None:
    n = 10
    days = _dates(n)
    seq = [100.0 + i for i in range(n)]
    px = _prices({d: [v] for d, v in zip(days, seq, strict=True)}, [ASSET_A])
    with pytest.raises(ValueError):
        volatility(px, window=1)
    with pytest.raises(ValueError):
        volatility(px, window=0)


def test_volatility_aliases() -> None:
    n = 80
    days = _dates(n)
    rng = np.random.default_rng(1)
    seq = list(100.0 + rng.normal(0.0, 1.0, size=n).cumsum())
    px = _prices({d: [v] for d, v in zip(days, seq, strict=True)}, [ASSET_A])
    pd.testing.assert_frame_equal(volatility_20d(px), volatility(px, window=20))
    pd.testing.assert_frame_equal(volatility_63d(px), volatility(px, window=63))


# ---------------------------------------------------------------------------
# Look-ahead safety — the anti-cheat contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factor_fn",
    [
        lambda px: rsi(px, period=14),
        lambda px: macd_hist(px),
        lambda px: volatility(px, window=10),
    ],
    ids=["rsi", "macd_hist", "volatility"],
)
def test_no_lookahead_changing_future_leaves_t_unchanged(factor_fn: Any) -> None:
    # 50 days of smooth-ish prices so all factors are finite near the middle.
    n = 50
    days = _dates(n)
    rng = np.random.default_rng(123)
    seq = list(100.0 + rng.normal(0.0, 1.0, size=n).cumsum())
    px = _prices({d: [v] for d, v in zip(days, seq, strict=True)}, [ASSET_A])

    base = factor_fn(px)

    # Perturb prices strictly AFTER decision date t (t = index 30).
    t_pos = 30
    future = seq.copy()
    for i in range(t_pos + 1, n):
        future[i] = future[i] * 2.0 + 10.0
    px_future = _prices({d: [v] for d, v in zip(days, future, strict=True)}, [ASSET_A])
    after = factor_fn(px_future)

    # Factor value at t must be identical regardless of future perturbation.
    assert base[ASSET_A].iloc[t_pos] == pytest.approx(after[ASSET_A].iloc[t_pos], nan_ok=True)
    # And every row up to and including t is identical.
    pd.testing.assert_series_equal(
        base[ASSET_A].iloc[: t_pos + 1],
        after[ASSET_A].iloc[: t_pos + 1],
        check_names=False,
    )
