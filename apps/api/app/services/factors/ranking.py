"""Cross-sectional ranking & normalization of factor values (FRA-51).

§14 factor-ranking primitives shared by IC (FRA-52), quantile backtest
(FRA-53), and sensitivity (FRA-54). Every transform is **cross-sectional**:
each row of the factor wide-frame (index = UTC midnight, columns = asset_id,
values = factor reading at that decision date) is an independent snapshot —
statistics are computed over the *assets present on that date only*, never
across time. That keeps each function look-ahead safe (§接口契约): a factor
reading at ``t`` maps to an output at ``t`` using solely information visible
at the ``t`` decision point.

NaN handling (assets missing on a date) mirrors the price wide-frame
convention inherited from the Week-2 engine (``app/services/backtest/types``):
NaNs are ignored by the per-date statistic (``skipna`` semantics) and the NaN
positions are preserved in the output. A cross-section with fewer than two
valid observations cannot produce a meaningful rank/z-score and degrades to
NaN for every asset on that date.

The four public functions are pure: no DB, no I/O, no mutation of the input
frame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "cross_sectional_rank",
    "quantile_bucket",
    "winsorize",
    "zscore",
]


def cross_sectional_rank(
    values: pd.DataFrame,
    *,
    ascending: bool = True,
) -> pd.DataFrame:
    """Per-date fractional (percentile) rank of each asset's factor value.

    For each decision date (row), ranks the cross-section of factor values and
    returns the percentile position in ``[0, 1]``. With ``ascending=True``
    (default) the largest factor value on a date ranks highest (rank pct → 1);
    pass ``ascending=False`` to invert. Ties get the average rank, so equal
    values share a percentile — the standard convention for factor research so
    IC (Spearman) and quantile bucketing agree.

    NaN positions are preserved: an asset absent on a date stays NaN rather
    than being assigned a phantom rank. A date with fewer than two valid
    observations yields all-NaN (no ordering is defined for a single point).

    Parameters
    ----------
    values:
        Factor wide-frame (index = UTC midnight, columns = asset_id). Input is
        not mutated.
    ascending:
        ``True`` → large factor value = high rank pct (default). ``False``
        inverts so the smallest value ranks highest.

    Returns
    -------
    pd.DataFrame
        Same index/columns/dtype as ``values``; cells are percentile ranks in
        ``[0, 1]`` or NaN where the input was NaN.
    """
    if values.shape[1] < 2:
        # Fewer than 2 assets → no cross-section to order; degrade to NaN.
        return _nan_frame_like(values)
    ranked = values.rank(axis=1, method="average", pct=True, ascending=ascending)
    # rank() over a row with < 2 valid cells: pandas returns 1.0 for a single
    # non-NaN value (n=1 → pct = rank/n = 1/1 = 1.0), which is meaningless for
    # a cross-sectional percentile. Mask those rows back to NaN.
    valid_counts = values.notna().sum(axis=1)
    sparse_rows = valid_counts < 2
    if sparse_rows.any():
        ranked.loc[sparse_rows] = np.nan
    return ranked


def zscore(
    values: pd.DataFrame,
    *,
    ddof: int = 0,
) -> pd.DataFrame:
    """Per-date z-score: ``(x - cross-section mean) / cross-section std``.

    Centers each date's factor distribution to mean ≈ 0 and scales to std ≈ 1,
    the standard normalization before averaging factors across dates or
    feeding IC / regression. ``ddof`` follows the NumPy convention
    (``ddof=0`` → population std, the default for z-scoring; ``ddof=1``
    → sample std).

    NaNs are skipped when computing each date's mean and std, so a missing
    asset does not drag the cross-section statistic toward zero. The NaN
    positions in the output mirror the input. A date with fewer than two
    valid observations (std undefined or zero) yields all-NaN: with one
    observation the mean equals the value (numerator zero) but the std is
    zero/undefined, so a z-score is not meaningful.

    Parameters
    ----------
    values:
        Factor wide-frame (index = UTC midnight, columns = asset_id).
    ddof:
        Delta degrees of freedom for the per-date std (0 = population).

    Returns
    -------
    pd.DataFrame
        Same index/columns/dtype; per-date standardized values or NaN where the
        input was NaN or the date had < 2 valid observations / zero variance.
    """
    if values.shape[1] < 2:
        return _nan_frame_like(values)
    mean = values.mean(axis=1, skipna=True)
    std = values.std(axis=1, skipna=True, ddof=ddof)
    # Dates with < 2 valid obs: std is NaN (pandas returns NaN for n<ddof+1).
    # Dates with zero variance (all-equal factor values): std == 0 → division
    # blows up. Both should degrade to NaN across the whole row.
    valid_counts = values.notna().sum(axis=1)
    bad = (valid_counts < 2) | std.isna() | (std <= 0.0)
    # Broadcast row stats across columns.
    z = values.sub(mean, axis=0).div(std, axis=0)
    if bad.any():
        z.loc[bad] = np.nan
    return z


def winsorize(
    values: pd.DataFrame,
    *,
    limits: tuple[float, float] = (0.05, 0.05),
) -> pd.DataFrame:
    """Per-date winsorization: clip outliers to the cross-section quantile bounds.

    For each date, assets below the ``limits[0]`` quantile are clipped up to
    that quantile's value and assets above the ``1 - limits[1]`` quantile are
    clipped down, taming extreme factor readings before ranking / z-scoring
    without discarding them. ``limits=(0.0, 0.0)`` disables clipping (returns
    a copy of the input).

    Quantiles are computed per date over the non-NaN cross-section, so missing
    assets do not affect the bounds; NaN positions are preserved. A date with
    fewer than two valid observations cannot resolve non-trivial quantiles and
    degrades to all-NaN.

    Parameters
    ----------
    values:
        Factor wide-frame (index = UTC midnight, columns = asset_id).
    limits:
        ``(lower, upper)`` tail fractions to clip; each in ``[0, 0.5]``. The
        default ``(0.05, 0.05)`` clips at the 5th and 95th percentiles.

    Returns
    -------
    pd.DataFrame
        Same index/columns/dtype; cells clipped to the per-date quantile bounds
        or NaN where the input was NaN.
    """
    lo, hi = limits
    if lo < 0.0 or hi < 0.0 or lo > 0.5 or hi > 0.5:
        raise ValueError(f"winsorize limits must be within [0, 0.5] on each side, got {limits}")
    if values.shape[1] < 2 or (lo == 0.0 and hi == 0.0):
        # No clipping requested OR too few columns to define a cross-section.
        return _nan_frame_like(values) if values.shape[1] < 2 else values.copy()

    # Per-date quantiles over the non-NaN cross-section. linear interpolation
    # matches the default for numpy/pandas quantile, giving a deterministic
    # bound even with modest asset counts.
    lower_q = values.quantile(lo, axis=1, numeric_only=False)
    upper_q = values.quantile(1.0 - hi, axis=1, numeric_only=False)
    clipped = values.clip(lower=lower_q, upper=upper_q, axis=0)
    # Dates with < 2 valid obs: quantile falls back to the single value (or
    # NaN), which would make clip a no-op rather than signalling "undefined".
    # Mask them to NaN to stay consistent with the other transforms.
    valid_counts = values.notna().sum(axis=1)
    sparse_rows = valid_counts < 2
    if sparse_rows.any():
        clipped.loc[sparse_rows] = np.nan
    return clipped


def quantile_bucket(
    values: pd.DataFrame,
    *,
    n_quantiles: int = 5,
) -> pd.DataFrame:
    """Per-date quantile bucket assignment (1 = lowest factor value, N = highest).

    Splits each date's cross-section into ``n_quantiles`` buckets of (near-)
    equal size and labels them ``1..N`` so that bucket 1 holds the smallest
    factor readings and bucket N the largest — the convention the quantile
    backtester (FRA-53) uses for its long-top / short-bottom spread. Bucket
    sizes differ by at most one when the asset count does not divide evenly.

    Assignment is rank-based rather than ``pd.qcut`` on raw values: each valid
    asset is assigned its average-rank position in ``[1, n]`` (NaNs excluded),
    then mapped to ``ceil(rank_pct * n_quantiles)`` clamped to ``[1, n]``. This
    keeps buckets balanced even with heavy ties or tiny cross-sections, where
    ``qcut`` raises or produces degenerate bins.

    NaN positions are preserved. A date with fewer than ``n_quantiles`` valid
    observations (or fewer than 2) degrades to all-NaN: you cannot carve
    ``n`` balanced buckets out of fewer than ``n`` points.

    Parameters
    ----------
    values:
        Factor wide-frame (index = UTC midnight, columns = asset_id).
    n_quantiles:
        Number of buckets (>= 1). The default 5 mirrors §14's canonical
        quintile stratification.

    Returns
    -------
    pd.DataFrame
        Same index/columns; cells are integer labels in ``[1, n_quantiles]]``
        or NaN where the input was NaN or the date had too few observations.
    """
    if n_quantiles < 1:
        raise ValueError(f"n_quantiles must be >= 1, got {n_quantiles}")

    if values.shape[1] < 2:
        return _nan_frame_like(values)

    # Average rank in [1, n_valid] per date, NaNs excluded.
    ranks = values.rank(axis=1, method="average", ascending=True)
    valid_counts = values.notna().sum(axis=1)

    # Map rank → bucket via the percentile. ceil(rank/n_valid * N) clamped to
    # [1, N] gives balanced buckets that differ in size by at most one.
    # rank_pct = (rank - 0.5) / n_valid  → the mid-point of each rank's
    # empirical CDF slot; ceil over [0,1] gives N balanced groups and keeps
    # ties in a single bucket rather than splitting them.
    n = float(n_quantiles)
    rank_pct = (ranks.sub(0.5, axis=0)).div(valid_counts.replace(0, np.nan), axis=0)
    # ceil in [0,1] * N → [1, N]; guard against fp underflow at the top.
    buckets = np.ceil(rank_pct.mul(n)).clip(upper=n, lower=1.0)

    # Dates with fewer than n_quantiles valid obs (or < 2) can't form N
    # balanced buckets → NaN.
    bad = (valid_counts < 2) | (valid_counts < n_quantiles)
    if bad.any():
        buckets.loc[bad] = np.nan

    return buckets


def _nan_frame_like(values: pd.DataFrame) -> pd.DataFrame:
    """Return an all-NaN frame with the same index/columns/dtype as ``values``.

    Used by the cross-sectional transforms when the input cannot support a
    cross-section (fewer than two asset columns): the output keeps the wide-frame
    contract (same index/columns) while signalling "no statistic available".
    """
    return pd.DataFrame(
        data=np.nan,
        index=values.index,
        columns=values.columns,
        dtype="float64",
    )
