"""Fixture news provider — packaged sample data, zero network (FRA-67).

Ships a small, hand-curated set of NVDA / AMD / QQQ headlines so the Week-4
sentiment demo and the test suite are fully reproducible without touching the
network. ``fetch`` filters the sample by asset symbol and the ``[start, end)``
publication window, mirroring the real provider contract (FRA-65).

This is the default provider (``NEWS_PROVIDER=fixture``): it makes the demo
deterministic and keeps ``make test`` offline. The sample headlines are
plausible-but-synthetic — they carry realistic publication timestamps so the
downstream factor-alignment and backtests exercise real time windows, but they
are not claims about real events.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.services.sentiment.providers.base import filter_window
from app.services.sentiment.types import NewsItem

# Packaged sample news. ``asset_id`` holds the provider-native symbol (the
# NewsProvider contract treats asset_ids as provider-native identifiers; the
# ingest service maps symbol -> DB UUID). ``published_at`` values are tz-aware
# UTC and span 2024-06-03..2024-06-07 so a typical Week-4 demo window captures
# several items per asset.
_SAMPLE_NEWS: tuple[NewsItem, ...] = (
    NewsItem(
        asset_id="NVDA",
        published_at=datetime(2024, 6, 3, 13, 30, tzinfo=UTC),
        source="fixture",
        headline="Nvidia announces next-generation Blackwell GPU platform",
        summary="Blackwell B200 targets a major leap in AI training throughput.",
        url="https://example.com/news/nvda-blackwell",
    ),
    NewsItem(
        asset_id="NVDA",
        published_at=datetime(2024, 6, 4, 14, 0, tzinfo=UTC),
        source="fixture",
        headline="NVDA hits fresh high on data-center demand",
        summary=None,
        url="https://example.com/news/nvda-high",
    ),
    NewsItem(
        asset_id="NVDA",
        published_at=datetime(2024, 6, 6, 16, 45, tzinfo=UTC),
        source="fixture",
        headline="Analysts raise NVDA price targets after Computex keynote",
        summary="Multiple sell-side shops lifted 12-month targets following the keynote.",
        url="https://example.com/news/nvda-targets",
    ),
    NewsItem(
        asset_id="AMD",
        published_at=datetime(2024, 6, 3, 15, 0, tzinfo=UTC),
        source="fixture",
        headline="AMD unveils MI325X accelerator to challenge Nvidia",
        summary=None,
        url="https://example.com/news/amd-mi325x",
    ),
    NewsItem(
        asset_id="AMD",
        published_at=datetime(2024, 6, 5, 13, 15, tzinfo=UTC),
        source="fixture",
        headline="AMD guides stronger server CPU revenue for H2",
        summary="Server franchise tracks a robust rack-scale ramp.",
        url="https://example.com/news/amd-server-guide",
    ),
    NewsItem(
        asset_id="AMD",
        published_at=datetime(2024, 6, 7, 17, 30, tzinfo=UTC),
        source="fixture",
        headline="AMD downgraded on near-term valuation concerns",
        summary=None,
        url="https://example.com/news/amd-downgrade",
    ),
    NewsItem(
        asset_id="QQQ",
        published_at=datetime(2024, 6, 4, 17, 0, tzinfo=UTC),
        source="fixture",
        headline="Nasdaq-100 breadth narrows as mega-caps lead",
        summary="Top-10 weightings push the index despite mixed breadth.",
        url="https://example.com/news/qqq-breadth",
    ),
    NewsItem(
        asset_id="QQQ",
        published_at=datetime(2024, 6, 6, 18, 30, tzinfo=UTC),
        source="fixture",
        headline="QQQ inflows hit record as AI optimism sustains tech bid",
        summary=None,
        url="https://example.com/news/qqq-inflows",
    ),
    NewsItem(
        asset_id="QQQ",
        published_at=datetime(2024, 6, 7, 19, 0, tzinfo=UTC),
        source="fixture",
        headline="QQQ fades into close as traders take profits before CPI",
        summary="Profit-taking ahead of the CPI print trimmed the week's gains.",
        url="https://example.com/news/qqq-fade",
    ),
)


class FixtureNewsProvider:
    """:class:`NewsProvider` backed by packaged sample data (FRA-67).

    Returns only sample items whose ``asset_id`` (symbol) is in ``asset_ids``
    and whose ``published_at`` falls in ``[start, end)``. Uncovered assets
    return no items — missing coverage stays missing (no synthesis, no
    forward-fill).
    """

    #: Stable key recorded in ``news_items.source``.
    name = "fixture"

    def __init__(self, samples: Sequence[NewsItem] | None = None) -> None:
        self._samples: tuple[NewsItem, ...] = (
            tuple(samples) if samples is not None else _SAMPLE_NEWS
        )

    def fetch(
        self,
        asset_ids: Sequence[str],
        start: datetime,
        end: datetime,
    ) -> list[NewsItem]:
        wanted = {a.upper() for a in asset_ids}
        matched = [it for it in self._samples if it.asset_id.upper() in wanted]
        return filter_window(matched, start, end)
