"""Daily sentiment factor — score aggregation to decision-date wide-frame (FRA-69).

Implements the :class:`~app.services.sentiment.protocols.SentimentFactor`
protocol from FRA-65. Converts item-level :class:`SentimentScore` instances
into a daily decision-date factor frame aligned to a trading calendar, following
the same wide-frame convention as Week-3 price/technical factors:
index = UTC-midnight decision dates, columns = ``str(asset_id)``.

Anti-cheat (FRA-65): each score's ``published_at`` is the earliest moment its
signal may be used. :meth:`DailySentimentFactor.compute` maps each score to the
first trading-calendar day **at or after** its publication — never to an earlier
day. Scores whose publication falls after the last calendar day are dropped
(their signal cannot inform any decision in the window). Missing coverage stays
``NaN`` — no forward-fill of stale sentiment across trading dates.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import numpy as np
import pandas as pd

from app.services.sentiment.protocols import SentimentFactor
from app.services.sentiment.types import SentimentLabel, SentimentScore, SentimentSummary


def _to_utc_timestamp(dt: datetime) -> pd.Timestamp:
    """Coerce *dt* to a tz-aware UTC :class:`~pandas.Timestamp`."""
    ts = pd.Timestamp(dt)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


class DailySentimentFactor(SentimentFactor):
    """Aggregate item-level scores into a daily mean-score factor frame.

    Maps each ``SentimentScore.published_at`` to the first trading-calendar day
    at or after it (``searchsorted(side="left")``), then groups by
    ``(signal_date, asset_id)`` and takes the mean ``score``. The result is
    reindexed to ``trading_calendar`` with ``NaN`` preserved for decision dates
    that have no mapped news (no forward-fill).

    The returned frame is drop-in compatible with Week-3 factor / IC / backtest
    pipelines: same index convention (UTC midnight), same column convention
    (``str(asset_id)``), same missing-data policy (explicit ``NaN``).
    """

    def compute(
        self,
        scores: Sequence[SentimentScore],
        trading_calendar: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Return a sentiment mean-score wide-frame aligned to *trading_calendar*.

        Each cell ``(date, asset)`` is the arithmetic mean of all scores whose
        ``published_at`` maps to that date for that asset. Cells with no news
        are ``NaN`` (not 0 — ``news_count == 0`` means missing coverage, not
        neutral sentiment).
        """
        if not isinstance(trading_calendar, pd.DatetimeIndex):
            raise TypeError("trading_calendar must be a pd.DatetimeIndex")
        if len(trading_calendar) == 0:
            raise ValueError("trading_calendar must not be empty")

        cal = trading_calendar
        cal = cal.tz_localize("UTC") if cal.tz is None else cal.tz_convert("UTC")

        if not scores:
            return pd.DataFrame(np.nan, index=cal, columns=[], dtype="float64")

        # Map each score's published_at → first trading day >= published_at.
        pub_values = pd.DatetimeIndex([_to_utc_timestamp(s.published_at) for s in scores])
        positions = cal.searchsorted(pub_values, side="left")

        # Drop scores that map past the last calendar day.
        valid_mask = positions < len(cal)
        if not valid_mask.any():
            return pd.DataFrame(np.nan, index=cal, columns=[], dtype="float64")

        # Build long-form records: (signal_date, asset_id, score).
        records: list[dict[str, object]] = []
        for i, score in enumerate(scores):
            if not valid_mask[i]:
                continue
            records.append(
                {
                    "signal_date": cal[positions[i]],
                    "asset_id": score.asset_id,
                    "score": score.score,
                }
            )
        long = pd.DataFrame(records)

        # Group by (signal_date, asset_id) → mean score, then pivot to wide.
        daily = long.groupby(["signal_date", "asset_id"], sort=True)["score"].mean()
        wide = daily.unstack("asset_id")
        wide.columns = [str(c) for c in wide.columns]

        # Reindex to the full calendar — NaN for days with no mapped news.
        wide = wide.reindex(cal)
        return wide.astype("float64")


def build_sentiment_summaries(
    scores: Sequence[SentimentScore],
    trading_calendar: pd.DatetimeIndex,
    *,
    model_name: str,
    prompt_version: str,
    window_days: int = 7,
) -> list[SentimentSummary]:
    """Build per ``(signal_date, asset_id)`` :class:`SentimentSummary` list.

    Unlike :meth:`DailySentimentFactor.compute` (which emits only the mean-score
    factor), this produces the full summary including ``news_count``,
    ``label_counts``, and the ``window_start`` / ``window_end`` text window.

    ``window_days`` controls how far back from each signal_date we look for
    scores to include in the aggregate (default 7 calendar days). A score is
    included in a signal_date's window iff its mapped signal_date equals that
    signal_date (i.e. only news that newly arrived since the previous trading
    day).
    """
    if not trading_calendar.size:
        return []

    cal = trading_calendar
    cal = cal.tz_localize("UTC") if cal.tz is None else cal.tz_convert("UTC")

    if not scores:
        return []

    pub_values = pd.DatetimeIndex([_to_utc_timestamp(s.published_at) for s in scores])
    positions = cal.searchsorted(pub_values, side="left")

    # Group valid scores by (signal_date, asset_id).
    grouped: dict[tuple[pd.Timestamp, str], list[SentimentScore]] = {}
    for i, score in enumerate(scores):
        pos = positions[i]
        if pos >= len(cal):
            continue
        key = (cal[pos], score.asset_id)
        grouped.setdefault(key, []).append(score)

    summaries: list[SentimentSummary] = []
    for (signal_date, asset_id), bucket in sorted(grouped.items()):
        pos = cal.get_loc(signal_date)
        window_start_idx = max(0, pos - window_days)
        window_end_idx = pos
        window_start = cal[window_start_idx].to_pydatetime()
        window_end = cal[window_end_idx].to_pydatetime()

        label_counts: dict[SentimentLabel, int] = {"positive": 0, "neutral": 0, "negative": 0}
        total_score = 0.0
        total_confidence = 0.0
        conf_count = 0
        for s in bucket:
            if s.label in label_counts:
                label_counts[s.label] += 1
            total_score += s.score
            if s.confidence is not None:
                total_confidence += s.confidence
                conf_count += 1

        n = len(bucket)
        summaries.append(
            SentimentSummary(
                asset_id=asset_id,
                signal_date=signal_date,
                window_start=window_start,
                window_end=window_end,
                model_name=model_name,
                prompt_version=prompt_version,
                score=total_score / n if n > 0 else None,
                confidence=total_confidence / conf_count if conf_count > 0 else None,
                news_count=n,
                label_counts=label_counts,
                source="computed",
                params={"window_days": window_days},
            )
        )
    return summaries
