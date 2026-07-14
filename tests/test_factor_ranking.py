"""Pure-unit tests for cross-sectional ranking & normalization (FRA-51).

No DB — every transform is a pure function of a factor value wide-frame; we
feed synthetic frames (tz-aware UTC midnight index, deterministic values, the
same convention as the Week-2 price wide-frame) and assert the cross-sectional
statistics per date. Coverage:

1. zscore 后每截面均值 ≈ 0(容差 1e-9)、std ≈ 1。
2. cross_sectional_rank ∈ [0,1],大值高 rank(ascending=True)。
3. cross_sectional_rank ascending=False 反转(小值高 rank)。
4. quantile_bucket 桶大小均衡(±1),1 = 最低、N = 最高。
5. NaN 不污染:含 NaN 截面其余资产的均值/std/rank 等于剔除 NaN 重算。
6. look-ahead 安全:截面标准化只用当日行,改其他 time 行不影响当日结果。
7. winsorize:极端值被截到分位边界,非极值不变。
8. 稀疏截面(< 2 个有效值)→ 全 NaN。
9. 单资产列(< 2 列)→ 全 NaN。
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from app.services.factors.ranking import (
    cross_sectional_rank,
    quantile_bucket,
    winsorize,
    zscore,
)

# ---------------------------------------------------------------------------
# helpers (mirror tests/test_backtest_strategies.py wide-frame builder)
# ---------------------------------------------------------------------------


def _ts(day: str) -> pd.Timestamp:
    """A tz-aware UTC-midnight timestamp (matches the wide-frame convention)."""
    return pd.Timestamp(datetime.fromisoformat(f"{day}T00:00:00"), tz="UTC")


def _factor_frame(
    day_values: dict[str, list[float]],
    asset_ids: list[str],
) -> pd.DataFrame:
    """Build a synthetic factor value wide-frame.

    ``day_values`` maps ISO date → per-asset factor value list (aligned with
    ``asset_ids``). Use ``float("nan")`` for absent assets.
    """
    days = sorted(day_values)
    index = pd.DatetimeIndex([_ts(d) for d in days])
    data = {aid: [day_values[d][i] for d in days] for i, aid in enumerate(asset_ids)}
    return pd.DataFrame(data, index=index, columns=asset_ids).astype("float64")


ASSETS = ["a", "b", "c", "d", "e", "f"]

# A single cross-section we reuse for deterministic assertions. Six assets,
# strictly increasing factor values so ranks/buckets are unambiguous.
ASC_DAY: dict[str, list[float]] = {
    "2024-01-02": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
}

# Two dates with different magnitudes — used to prove look-ahead safety (the
# per-date transform on day 1 is invariant to day 2's values).
TWO_DAYS: dict[str, list[float]] = {
    "2024-01-02": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    "2024-01-03": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
}


# ---------------------------------------------------------------------------
# 1) zscore — per-date mean ≈ 0, std ≈ 1
# ---------------------------------------------------------------------------


def test_zscore_centered_per_cross_section() -> None:
    frame = _factor_frame(ASC_DAY, ASSETS)
    z = zscore(frame)

    row = z.iloc[0].dropna()
    assert abs(row.mean()) < 1e-9
    # ddof=0 (population) → std exactly 1 over a centered cross-section.
    assert row.std(ddof=0) == pytest.approx(1.0, abs=1e-9)
    # Input has no NaN → output has none either.
    assert not z.isna().any().any()


def test_zscore_two_dates_independent_normalization() -> None:
    frame = _factor_frame(TWO_DAYS, ASSETS)
    z = zscore(frame)
    # Each date independently centered — day 2 is 10× day 1 but both z-score
    # to the same standardized cross-section.
    pd.testing.assert_series_equal(z.iloc[0], z.iloc[1], check_names=False, check_index=False)
    # Sanity: smallest value (a) is the most negative, largest (f) most positive.
    assert z.loc[_ts("2024-01-02"), "a"] < z.loc[_ts("2024-01-02"), "f"]


def test_zscore_ddof_one_changes_scale() -> None:
    # ddof=1 → sample std divides by (n-1), so std is larger than population
    # std by sqrt(n/(n-1)); therefore |z1| is *smaller* than |z0| by the
    # reciprocal factor sqrt((n-1)/n).
    frame = _factor_frame(ASC_DAY, ASSETS)
    z0 = zscore(frame, ddof=0)
    z1 = zscore(frame, ddof=1)
    ratio = z1.iloc[0].abs().max() / z0.iloc[0].abs().max()
    assert ratio == pytest.approx(np.sqrt(5.0 / 6.0), rel=1e-9)


# ---------------------------------------------------------------------------
# 2 & 3) cross_sectional_rank ∈ [0,1], ordering & ascending flag
# ---------------------------------------------------------------------------


def test_rank_in_unit_interval_and_ordering() -> None:
    frame = _factor_frame(ASC_DAY, ASSETS)
    r = cross_sectional_rank(frame)
    row = r.iloc[0]
    assert (row.dropna() >= 0.0).all() and (row.dropna() <= 1.0).all()
    # Largest factor value (f=6.0) → highest rank pct.
    assert row["f"] == pytest.approx(1.0)
    # Smallest (a=1.0) → lowest non-zero rank pct (1/6).
    assert row["a"] == pytest.approx(1.0 / 6.0)
    # Monotone increasing with factor value.
    vals = [row[aid] for aid in ASSETS]
    assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))


def test_rank_descending_inverts_order() -> None:
    frame = _factor_frame(ASC_DAY, ASSETS)
    r = cross_sectional_rank(frame, ascending=False)
    row = r.iloc[0]
    # Smallest value now ranks highest.
    assert row["a"] == pytest.approx(1.0)
    assert row["f"] == pytest.approx(1.0 / 6.0)


def test_rank_ties_share_average_percentile() -> None:
    # Three equal values share the average of ranks 1,2,3 (=2) → pct 2/3.
    frame = _factor_frame({"2024-01-02": [5.0, 5.0, 5.0, 10.0]}, ["a", "b", "c", "d"])
    r = cross_sectional_rank(frame).iloc[0]
    shared = r["a"]
    assert r["a"] == r["b"] == r["c"] == shared
    assert shared == pytest.approx(2.0 / 4.0)
    assert r["d"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 4) quantile_bucket — balanced sizes, 1 = lowest, N = highest
# ---------------------------------------------------------------------------


def test_quantile_bucket_balanced_and_ordered() -> None:
    # 10 assets, 5 buckets → exactly 2 per bucket.
    assets10 = [f"a{i}" for i in range(10)]
    frame = _factor_frame(
        {"2024-01-02": [float(i) for i in range(10)]},
        assets10,
    )
    b = quantile_bucket(frame, n_quantiles=5).iloc[0]
    # Bucket labels in [1, 5]; integer-valued.
    assert b.dropna().between(1, 5).all()
    assert (b.dropna() % 1 == 0).all()
    # Exactly 2 per bucket (balanced).
    counts = b.value_counts().to_dict()
    assert sorted(counts.values()) == [2, 2, 2, 2, 2]
    # 1 = lowest factor value, 5 = highest.
    assert b["a0"] == 1.0
    assert b["a9"] == 5.0
    # Monotone: bucket increases with factor value.
    buckets = [b[aid] for aid in assets10]
    assert all(buckets[i] <= buckets[i + 1] for i in range(len(buckets) - 1))


def test_quantile_bucket_uneven_split_balanced() -> None:
    # 7 assets, 3 buckets → sizes 3,2,2 (differ by at most one).
    assets7 = [f"a{i}" for i in range(7)]
    frame = _factor_frame(
        {"2024-01-02": [float(i) for i in range(7)]},
        assets7,
    )
    b = quantile_bucket(frame, n_quantiles=3).iloc[0]
    counts = sorted(b.value_counts().to_list())
    assert counts[-1] - counts[0] <= 1
    assert sum(counts) == 7
    # Lowest → bucket 1, highest → bucket 3.
    assert b["a0"] == 1.0
    assert b["a6"] == 3.0


def test_quantile_bucket_single_quantile_all_one() -> None:
    frame = _factor_frame(ASC_DAY, ASSETS)
    b = quantile_bucket(frame, n_quantiles=1).iloc[0]
    assert (b.dropna() == 1.0).all()


def test_quantile_bucket_rejects_nonpositive_n() -> None:
    frame = _factor_frame(ASC_DAY, ASSETS)
    with pytest.raises(ValueError):
        quantile_bucket(frame, n_quantiles=0)


# ---------------------------------------------------------------------------
# 5) NaN does not pollute the cross-section
# ---------------------------------------------------------------------------


def test_nan_excluded_from_cross_section_statistics() -> None:
    # 6 assets but c & e missing on this date.
    day = {"2024-01-02": [1.0, 2.0, float("nan"), 4.0, float("nan"), 6.0]}
    frame = _factor_frame(day, ASSETS)
    # Ground-truth: drop NaN, recompute on the 4 survivors [1,2,4,6].
    survivors = pd.Series([1.0, 2.0, 4.0, 6.0])

    z = zscore(frame).iloc[0]
    # NaN positions preserved.
    assert pd.isna(z["c"])
    assert pd.isna(z["e"])
    # Survivors match the dropna z-score exactly.
    expected_z = (survivors - survivors.mean()) / survivors.std(ddof=0)
    for aid, val in zip(["a", "b", "d", "f"], expected_z, strict=True):
        assert z[aid] == pytest.approx(val, abs=1e-9)
    # The survivors' mean is ~0 after z-scoring.
    assert abs(z[["a", "b", "d", "f"]].mean()) < 1e-9

    r = cross_sectional_rank(frame).iloc[0]
    assert pd.isna(r["c"]) and pd.isna(r["e"])
    # Ranks computed over 4 survivors: [1,2,4,6] → pct [0.25, 0.5, 0.75, 1.0].
    assert r["a"] == pytest.approx(1.0 / 4.0)
    assert r["f"] == pytest.approx(1.0)


def test_nan_excluded_from_winsorize_and_buckets() -> None:
    day = {"2024-01-02": [1.0, 2.0, float("nan"), 4.0, float("nan"), 6.0]}
    frame = _factor_frame(day, ASSETS)
    w = winsorize(frame, limits=(0.05, 0.05)).iloc[0]
    # NaN positions preserved.
    assert pd.isna(w["c"]) and pd.isna(w["e"])
    # Survivors unchanged in interior, extremes clipped to per-date bounds.
    survivors = pd.Series([1.0, 2.0, 4.0, 6.0])
    lo, hi = survivors.quantile(0.05), survivors.quantile(0.95)
    assert w["a"] == pytest.approx(lo)
    assert w["f"] == pytest.approx(hi)
    assert w["b"] == pytest.approx(2.0)

    b = quantile_bucket(frame, n_quantiles=2).iloc[0]
    assert pd.isna(b["c"]) and pd.isna(b["e"])
    # Low half → bucket 1, high half → bucket 2.
    assert b["a"] == 1.0 and b["b"] == 1.0
    assert b["d"] == 2.0 and b["f"] == 2.0


# ---------------------------------------------------------------------------
# 6) look-ahead safety — per-date invariance
# ---------------------------------------------------------------------------


def test_per_date_transform_invariant_to_other_dates() -> None:
    # Day 1 alone vs day 1 + a wildly different day 2 → same day-1 output.
    day1_frame = _factor_frame({"2024-01-02": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, ASSETS)
    two_day_frame = _factor_frame(TWO_DAYS, ASSETS)

    for fn in (
        lambda f: zscore(f),
        lambda f: cross_sectional_rank(f),
        lambda f: winsorize(f, limits=(0.05, 0.05)),
        lambda f: quantile_bucket(f, n_quantiles=3),
    ):
        alone = fn(day1_frame).iloc[0]
        with_other = fn(two_day_frame).loc[_ts("2024-01-02")]
        pd.testing.assert_series_equal(alone, with_other, check_names=False)


# ---------------------------------------------------------------------------
# 7) winsorize — extremes clipped to quantile bounds
# ---------------------------------------------------------------------------


def test_winsorize_clips_extremes_only() -> None:
    # 20 assets 1..20; 5%/95% bounds clip min & max to the quantile values,
    # interior untouched.
    assets20 = [f"a{i}" for i in range(20)]
    vals = [float(i) for i in range(1, 21)]
    frame = _factor_frame({"2024-01-02": vals}, assets20)
    w = winsorize(frame, limits=(0.05, 0.05)).iloc[0]
    s = pd.Series(vals)
    lo, hi = s.quantile(0.05), s.quantile(0.95)
    # Smallest clipped up to lo, largest clipped down to hi.
    assert w["a0"] == pytest.approx(lo)
    assert w["a19"] == pytest.approx(hi)
    # Interior (say a5..a14) untouched.
    for i in range(5, 15):
        assert w[f"a{i}"] == pytest.approx(float(i + 1))


def test_winsorize_zero_limits_is_identity() -> None:
    frame = _factor_frame(ASC_DAY, ASSETS)
    w = winsorize(frame, limits=(0.0, 0.0))
    pd.testing.assert_frame_equal(w, frame)
    # And returns a copy (not the same object).
    assert w is not frame


def test_winsorize_rejects_invalid_limits() -> None:
    frame = _factor_frame(ASC_DAY, ASSETS)
    with pytest.raises(ValueError):
        winsorize(frame, limits=(-0.1, 0.05))
    with pytest.raises(ValueError):
        winsorize(frame, limits=(0.6, 0.05))


# ---------------------------------------------------------------------------
# 8) sparse cross-section (< 2 valid) → all-NaN row
# ---------------------------------------------------------------------------


def test_sparse_cross_section_degrades_to_nan() -> None:
    # One date with a single valid asset, one all-NaN date.
    day = {
        "2024-01-02": [1.0, float("nan"), float("nan"), float("nan"), float("nan"), float("nan")],
        "2024-01-03": [float("nan")] * 6,
    }
    frame = _factor_frame(day, ASSETS)
    for fn in (
        lambda f: zscore(f),
        lambda f: cross_sectional_rank(f),
        lambda f: winsorize(f, limits=(0.05, 0.05)),
        lambda f: quantile_bucket(f, n_quantiles=2),
    ):
        out = fn(frame)
        # Both rows all-NaN: single-asset & empty cross-sections are undefined.
        assert out.iloc[0].isna().all(), fn
        assert out.iloc[1].isna().all(), fn


def test_zero_variance_cross_section_zscore_is_nan() -> None:
    # All-equal factor values → std 0 → z-score undefined → NaN row.
    day = {"2024-01-02": [3.0, 3.0, 3.0, 3.0]}
    frame = _factor_frame(day, ["a", "b", "c", "d"])
    z = zscore(frame).iloc[0]
    assert z.isna().all()


# ---------------------------------------------------------------------------
# 9) single-asset column (< 2 columns) → all-NaN, contract preserved
# ---------------------------------------------------------------------------


def test_single_column_frame_returns_all_nan_preserving_shape() -> None:
    frame = _factor_frame({"2024-01-02": [1.0]}, ["a"])
    for fn in (
        lambda f: zscore(f),
        lambda f: cross_sectional_rank(f),
        lambda f: winsorize(f, limits=(0.05, 0.05)),
        lambda f: quantile_bucket(f, n_quantiles=2),
    ):
        out = fn(frame)
        assert out.shape == frame.shape
        assert list(out.columns) == ["a"]
        assert list(out.index) == list(frame.index)
        assert out.isna().all().all()


def test_does_not_mutate_input() -> None:
    frame = _factor_frame(ASC_DAY, ASSETS)
    original = frame.copy(deep=True)
    for fn in (
        lambda f: zscore(f),
        lambda f: cross_sectional_rank(f),
        lambda f: winsorize(f, limits=(0.05, 0.05)),
        lambda f: quantile_bucket(f, n_quantiles=3),
    ):
        fn(frame)
    pd.testing.assert_frame_equal(frame, original)
