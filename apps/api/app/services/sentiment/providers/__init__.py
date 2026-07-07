"""Pluggable news-provider registry + dispatcher (FRA-67).

The single entry point :func:`get_news_provider` routes a provider key to the
matching :class:`~app.services.sentiment.protocols.NewsProvider` adapter. New
providers are added by registering a factory here — the worker and (future)
API read :data:`SUPPORTED_NEWS_PROVIDERS` from this module, so adding a source
needs no change outside it.

Two providers ship today:

* ``fixture`` — packaged NVDA/AMD/QQQ sample data; the default, makes the
  Week-4 demo and ``make test`` fully reproducible without the network.
* ``yfinance`` — real headlines via ``yfinance.Ticker(symbol).news``; reuses
  the existing yfinance dependency (no new API key), with the provider applying
  the ``[start, end)`` window and per-asset caps client-side.

The yfinance per-asset cap is read from ``settings.news_max_items_per_asset``
inside its factory, so a config change takes effect on the next dispatch
without touching app/worker startup.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.config import settings
from app.services.sentiment.protocols import NewsProvider
from app.services.sentiment.providers.fixture import FixtureNewsProvider
from app.services.sentiment.providers.yfinance import YfinanceNewsProvider

__all__ = [
    "FixtureNewsProvider",
    "SUPPORTED_NEWS_PROVIDERS",
    "YfinanceNewsProvider",
    "get_news_provider",
]


# Provider key → zero-arg factory. Reading the yfinance per-asset cap lazily
# (inside the factory) means a config change is picked up on the next dispatch
# without reimporting, and a misconfigured cap never blocks app/worker startup.
_FACTORIES: dict[str, Callable[[], NewsProvider]] = {
    "fixture": lambda: FixtureNewsProvider(),
    "yfinance": lambda: YfinanceNewsProvider(
        max_items_per_asset=settings.news_max_items_per_asset,
    ),
}

# Derived from the registry so the allow-list can never drift from the adapters.
SUPPORTED_NEWS_PROVIDERS: tuple[str, ...] = tuple(_FACTORIES.keys())


def get_news_provider(key: str | None = None) -> NewsProvider:
    """Return the :class:`NewsProvider` adapter for ``key``.

    ``key=None`` falls back to ``settings.news_provider`` so callers can omit the
    argument and still respect operator config. Raises :class:`ValueError` for an
    unknown key so the caller (worker / API) can surface it as an input/config
    error rather than a silent miss.
    """
    resolved = key if key is not None else settings.news_provider
    factory = _FACTORIES.get(resolved)
    if factory is None:
        raise ValueError(
            f"unsupported news provider: {resolved!r}; expected one of {SUPPORTED_NEWS_PROVIDERS}"
        )
    return factory()
