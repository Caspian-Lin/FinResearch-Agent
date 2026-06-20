"""Pure-unit tests for factor IC evaluation (FRA-52).

No DB — IC is a pure function of a factor value wide-frame and a forward-return
wide-frame (both tz-aware UTC midnight index, asset_id columns, the Week-2/3
convention). We feed synthetic frames and assert per-date Spearman rank IC and
the aggregate ICSummary statistics. Coverage:

1. ``forward_returns`` aligns to t→t+h and tails NaN; rejects horizon ≤ 0.
2. IC = ±1 for perfectly monotone / reverse-monotone cross-sections.
3. ``summarize_ic`` mean / ICIR / t-stat / p-value / n / positive-rate match
   hand-computed formulas (p-value via the normal approximation ``erfc``).
4. Warmup / too-few-valid-asset rows → NaN IC (never leaks future data).
5. NaN assets excluded pairwise per cross-section.
6. ``RankIC`` satisfies the ``InformationCoefficient`` protocol.
7. (optional scipy) per-row IC aligns with ``scipy.stats.spearmanr``.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from app.services.factors.evaluation import (
    RankIC,
    evaluate_ic,
    forward_returns,
    ic_series,
    summarize_ic,
)
from app.services.factors.protocols import InformationCoefficient
from app.services.factors.types import ICResult

try:  # optional — only used to assert per-row IC alignment when available
    from scipy.stats import spearmanr as _scipy_spearmanr

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# ---------------------------------------------------------------------------
# helpers (mirror tests/test_factor_ranking.py wide-frame builder)
# ---------------------------------------------------------------------------


def _ts(day: str) -> pd.Timestamp:
    """A tz-aware UTC-midnight timestamp (matches the wide-frame convention)."""
    return pd.Timestamp(datetime.fromisoformat(f"{day}T00:00:00"), tz="UTC")


def _frame(day_values: dict[str, list[float]], asset_ids: list[str]) -> pd.DataFrame:
    """Build a synthetic wide-frame (factor values OR forward returns OR prices)."""
    days = sorted(day_values)
    index = pd.DatetimeIndex([_ts(d) for d in days])
    data = {aid: [day_values[d][i] for d in days] for i, aid in enumerate(asset_ids)}
    return pd.DataFrame(data, index=index, columns=asset_ids).astype("float64")


ASSETS = ["a", "b", "c", "d", "e"]
NAN = float("nan")


# ---------------------------------------------------------------------------
# forward_returns
# ---------------------------------------------------------------------------


def test_forward_returns_alignment_and_tail_nan() -> None:
    # Single asset rising 10% per day: 100 → 110 → 121 → 133.1 → 146.41
    prices = _frame(
        {
            "2024-01-01": [100.0],
            "2024-01-02": [110.0],
            "2024-01-03": [121.0],
            "2024-01-04": [133.1],
            "2024-01-05": [146.41],
        },
        ["a"],
    )
    fr1 = forward_returns(prices, 1)
    np.testing.assert_allclose(fr1["a"].to_numpy()[:4], [0.1, 0.1, 0.1, 0.1], rtol=1e-9)
    assert math.isnan(fr1["a"].iloc[4])  # last bar has no future

    fr2 = forward_returns(prices, 2)
    # 100→121 = +21%, 110→133.1 = +21%, 121→146.41 = +21%
    np.testing.assert_allclose(fr2["a"].to_numpy()[:3], [0.21, 0.21, 0.21], rtol=1e-9)
    assert math.isnan(fr2["a"].iloc[3]) and math.isnan(fr2["a"].iloc[4])


def test_forward_returns_rejects_nonpositive_horizon() -> None:
    prices = _frame({"2024-01-01": [1.0]}, ["a"])
    with pytest.raises(ValueError):
        forward_returns(prices, 0)
    with pytest.raises(ValueError):
        forward_returns(prices, -3)


# ---------------------------------------------------------------------------
# ic_series — per-date Spearman rank IC
# ---------------------------------------------------------------------------


def test_ic_series_perfect_monotone_and_reverse() -> None:
    factor = _frame(
        {
            "2024-01-01": [1.0, 2.0, 3.0, 4.0, 5.0],
            "2024-01-02": [1.0, 2.0, 3.0, 4.0, 5.0],
        },
        ASSETS,
    )
    forward = _frame(
        {
            "2024-01-01": [5.0, 4.0, 3.0, 2.0, 1.0],  # reverse → IC = -1
            "2024-01-02": [1.0, 2.0, 3.0, 4.0, 5.0],  # same → IC = +1
        },
        ASSETS,
    )
    s = ic_series(factor, forward)
    assert s.shape[0] == 2
    np.testing.assert_allclose(s.to_numpy(), [-1.0, 1.0], rtol=1e-9)


def test_ic_series_nan_when_too_few_valid_assets() -> None:
    # Only one jointly-valid asset on day 1 → IC undefined
    factor = _frame({"2024-01-01": [1.0, NAN, NAN, NAN, NAN]}, ASSETS)
    forward = _frame({"2024-01-01": [2.0, NAN, NAN, NAN, NAN]}, ASSETS)
    s = ic_series(factor, forward)
    assert math.isnan(s.iloc[0])


def test_ic_series_excludes_nan_pairwise() -> None:
    # Asset e missing on day 1; the remaining 4 are perfectly monotone → IC = 1
    factor = _frame({"2024-01-01": [1.0, 2.0, 3.0, 4.0, NAN]}, ASSETS)
    forward = _frame({"2024-01-01": [10.0, 20.0, 30.0, 40.0, NAN]}, ASSETS)
    s = ic_series(factor, forward)
    assert s.iloc[0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# summarize_ic
# ---------------------------------------------------------------------------


def test_summarize_ic_statistics() -> None:
    vals = [0.1, 0.2, -0.1, 0.3]
    s = pd.Series(vals, index=pd.DatetimeIndex([_ts(f"2024-01-0{i}") for i in range(1, 5)]))
    summary = summarize_ic(s)

    mean = 0.125
    std = float(pd.Series(vals).std(ddof=1))  # sample std, reference
    expected_t = math.sqrt(4) * mean / std

    assert summary.n == 4
    assert summary.mean == pytest.approx(mean)
    assert summary.icir == pytest.approx(mean / std)
    assert summary.t_stat == pytest.approx(expected_t)
    assert summary.p_value == pytest.approx(math.erfc(abs(expected_t) / math.sqrt(2.0)))
    assert summary.positive_rate == pytest.approx(0.75)


def test_summarize_ic_skips_nan() -> None:
    s = pd.Series(
        [0.1, NAN, 0.3, NAN],
        index=pd.DatetimeIndex([_ts(f"2024-01-0{i}") for i in range(1, 5)]),
    )
    summary = summarize_ic(s)
    assert summary.n == 2
    assert summary.mean == pytest.approx(0.2)


def test_summarize_ic_all_nan_returns_empty_summary() -> None:
    s = pd.Series([NAN, NAN], index=pd.DatetimeIndex([_ts("2024-01-01"), _ts("2024-01-02")]))
    summary = summarize_ic(s)
    assert summary.n == 0
    assert math.isnan(summary.mean)
    assert math.isnan(summary.t_stat)


def test_summarize_ic_zero_std_yields_nan_irr() -> None:
    # Constant IC → zero variance → ICIR / t-stat undefined
    s = pd.Series(
        [0.2, 0.2, 0.2],
        index=pd.DatetimeIndex([_ts(f"2024-01-0{i}") for i in range(1, 4)]),
    )
    summary = summarize_ic(s)
    assert summary.n == 3
    assert summary.mean == pytest.approx(0.2)
    assert math.isnan(summary.icir)
    assert math.isnan(summary.t_stat)


# ---------------------------------------------------------------------------
# RankIC / evaluate_ic
# ---------------------------------------------------------------------------


def test_rankic_satisfies_information_coefficient_protocol() -> None:
    assert isinstance(RankIC(), InformationCoefficient)


def test_evaluate_ic_returns_result_with_series_and_summary() -> None:
    factor = _frame(
        {
            "2024-01-01": [1.0, 2.0, 3.0, 4.0, 5.0],
            "2024-01-02": [5.0, 4.0, 3.0, 2.0, 1.0],
        },
        ASSETS,
    )
    forward = _frame(
        {
            "2024-01-01": [1.0, 2.0, 3.0, 4.0, 5.0],
            "2024-01-02": [1.0, 2.0, 3.0, 4.0, 5.0],
        },
        ASSETS,
    )
    result = evaluate_ic(factor, forward)
    assert isinstance(result, ICResult)
    assert result.series.shape[0] == 2
    assert result.summary.n == 2
    np.testing.assert_allclose(result.series.to_numpy(), [1.0, -1.0], rtol=1e-9)


# ---------------------------------------------------------------------------
# optional scipy alignment
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_SCIPY, reason="scipy not installed (optional)")
def test_ic_aligns_with_scipy_spearmanr() -> None:
    rng = np.random.default_rng(42)
    n_days, n_assets = 8, 6
    raw_f = rng.normal(size=(n_days, n_assets))
    raw_r = rng.normal(size=(n_days, n_assets))
    # poke a couple of NaNs to exercise pairwise exclusion
    raw_f[2, 1] = NAN
    raw_r[5, 3] = NAN
    days = [f"2024-01-{i:02d}" for i in range(1, n_days + 1)]
    factor = pd.DataFrame(raw_f, index=pd.DatetimeIndex([_ts(d) for d in days]))
    forward = pd.DataFrame(raw_r, index=pd.DatetimeIndex([_ts(d) for d in days]))
    s = ic_series(factor, forward)
    for i, t in enumerate(factor.index):
        x = raw_f[i]
        y = raw_r[i]
        mask = ~(np.isnan(x) | np.isnan(y))
        if mask.sum() < 2:
            assert math.isnan(s.loc[t])
            continue
        rho, _ = _scipy_spearmanr(x[mask], y[mask])
        assert s.loc[t] == pytest.approx(float(rho), abs=1e-9)
