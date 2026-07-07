"""yfinance news provider — real headline fetch via yfinance.Ticker (FRA-67).

Fetches recent news per symbol through ``yfinance.Ticker(symbol).news`` and
normalizes each item to a :class:`~app.services.sentiment.types.NewsItem`.
yfinance exposes no server-side window filter (it returns only the most recent
feed), so the provider applies the ``[start, end)`` window client-side and caps
per-asset counts. Transient network/rate-limit errors are retried via the
shared retryer (injectable for tests).

The provider never touches the DB: ``asset_id`` on returned items is the
provider-native symbol, and the ingest service maps symbol -> DB UUID. The
raw source dict is preserved in ``params["raw"]`` so the service layer can write
an auditable ``raw_payload`` (FRA-66 anti-cheat / reproducibility requirement).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from tenacity import Retrying

from app.services.datasources.base import build_default_retryer
from app.services.sentiment.providers.base import coerce_published_at
from app.services.sentiment.types import NewsItem

logger = logging.getLogger(__name__)


class YfinanceNewsProvider:
    """:class:`NewsProvider` backed by ``yfinance.Ticker(symbol).news`` (FRA-67).

    Returned items carry ``source="yfinance"`` and a tz-aware ``published_at``.
    An uncovered symbol yields no items (empty feed or all out-of-window) — the
    provider never synthesizes rows. Per-asset output is capped at
    ``max_items_per_asset`` to bound ingestion from this volatile feed.
    """

    #: Stable key recorded in ``news_items.source``.
    name = "yfinance"

    def __init__(
        self,
        retryer: Retrying | None = None,
        max_items_per_asset: int = 100,
    ) -> None:
        self._retryer = retryer
        self._max_items_per_asset = max_items_per_asset

    def _fetch_feed(self, symbol: str) -> list[dict[str, Any]]:
        """Return the raw yfinance news feed for ``symbol`` (retried)."""
        import yfinance as yf

        def _do_fetch() -> list[dict[str, Any]]:
            feed = yf.Ticker(symbol).news
            return list(feed) if feed else []

        retryer: Retrying = self._retryer if self._retryer is not None else build_default_retryer()
        return retryer(_do_fetch)

    def fetch(
        self,
        asset_ids: Sequence[str],
        start: datetime,
        end: datetime,
    ) -> list[NewsItem]:
        items: list[NewsItem] = []
        for symbol in asset_ids:
            try:
                raw_list = self._fetch_feed(symbol)
            except Exception:
                # A transient failure that exhausted retries surfaces here; log
                # and continue so one symbol's outage doesn't lose the rest of
                # the universe. The ingest service reports partial-coverage
                # warnings; a fully-empty result still succeeds with status
                # success_no_data (mirrors sync_ohlcv's empty-feed handling).
                logger.exception("yfinance news fetch failed for symbol=%s", symbol)
                continue

            kept = 0
            for raw in raw_list:
                if kept >= self._max_items_per_asset:
                    break
                try:
                    published_at = coerce_published_at(raw.get("providerPublishTime"))
                except (TypeError, ValueError):
                    logger.warning(
                        "yfinance news: skipping item with unparseable publish time for %s",
                        symbol,
                    )
                    continue
                if not (start <= published_at < end):
                    continue
                headline = str(raw.get("title", "")).strip()
                if not headline:
                    continue
                items.append(
                    NewsItem(
                        asset_id=symbol,
                        published_at=published_at,
                        source=self.name,
                        headline=headline,
                        summary=raw.get("summary") or None,
                        url=raw.get("link") or None,
                        params={"publisher": raw.get("publisher"), "raw": raw},
                    )
                )
                kept += 1
        return items
