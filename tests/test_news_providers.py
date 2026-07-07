"""News provider + registry tests (FRA-67).

Covers the dispatcher (:func:`get_news_provider` + :data:`SUPPORTED_NEWS_PROVIDERS`),
the ``FixtureNewsProvider`` packaged-sample path, and the ``YfinanceNewsProvider``
field-conversion path.

yfinance is an optional dependency and is not exercised against the network in
CI: the provider's lazy ``import yfinance`` is intercepted by injecting a fake
module into ``sys.modules`` — no network, no real library. The fake returns a
hand-built news feed in yfinance's native dict shape so the adapter's timestamp
coercion, window filter, and per-asset cap are exercised for real.

No DB: these are pure provider-layer unit tests. The ingestion/upsert paths
(``sync_news`` + ``upsert_news_items``) live in ``test_news_ingestion.py``.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from app.services.sentiment.protocols import NewsProvider
from app.services.sentiment.providers import (
    SUPPORTED_NEWS_PROVIDERS,
    FixtureNewsProvider,
    YfinanceNewsProvider,
    get_news_provider,
)
from app.services.sentiment.providers.base import coerce_published_at, filter_window
from app.services.sentiment.types import NewsItem

UTC_NOW = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Dispatcher + SUPPORTED_NEWS_PROVIDERS
# ---------------------------------------------------------------------------


def test_supported_news_providers_lists_both() -> None:
    assert SUPPORTED_NEWS_PROVIDERS == ("fixture", "yfinance")


def test_get_news_provider_routes_known_providers() -> None:
    fx = get_news_provider("fixture")
    yf = get_news_provider("yfinance")
    assert isinstance(fx, FixtureNewsProvider)
    assert isinstance(yf, YfinanceNewsProvider)
    assert fx.name == "fixture"
    assert yf.name == "yfinance"


def test_get_news_provider_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unsupported news provider"):
        get_news_provider("bloomberg")


def test_get_news_provider_none_falls_back_to_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.sentiment.providers as prov_mod

    captured: dict[str, object] = {}

    class _Sentinel(FixtureNewsProvider):
        def __init__(self) -> None:  # noqa: D401
            super().__init__()
            captured["constructed"] = True

    monkeypatch.setattr(prov_mod.settings, "news_provider", "fixture")
    monkeypatch.setitem(prov_mod._FACTORIES, "fixture", lambda: _Sentinel())
    provider = get_news_provider(None)
    assert captured.get("constructed") is True
    assert isinstance(provider, _Sentinel)


# ---------------------------------------------------------------------------
# coerce_published_at
# ---------------------------------------------------------------------------


def test_coerce_published_at_int_epoch() -> None:
    ts = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    assert coerce_published_at(int(ts.timestamp())) == ts


def test_coerce_published_at_float_epoch() -> None:
    ts = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    assert coerce_published_at(float(ts.timestamp())) == ts


def test_coerce_published_at_iso_with_z() -> None:
    assert coerce_published_at("2024-06-03T13:30:00Z") == datetime(2024, 6, 3, 13, 30, tzinfo=UTC)


def test_coerce_published_at_iso_with_offset() -> None:
    # 09:30-04:00 == 13:30 UTC
    assert coerce_published_at("2024-06-03T09:30:00-04:00") == datetime(
        2024, 6, 3, 13, 30, tzinfo=UTC
    )


def test_coerce_published_at_naive_datetime_assumed_utc() -> None:
    naive = datetime(2024, 6, 3, 13, 30)
    out = coerce_published_at(naive)
    assert out == datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    assert out.tzinfo is not None


def test_coerce_published_at_aware_datetime_passes_through() -> None:
    aware = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    assert coerce_published_at(aware) is aware


def test_coerce_published_at_bool_rejected() -> None:
    with pytest.raises(TypeError, match="bool"):
        coerce_published_at(True)


def test_coerce_published_at_unsupported_type_rejected() -> None:
    with pytest.raises(TypeError, match="NoneType"):
        coerce_published_at(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# filter_window — [start, end) half-open semantics
# ---------------------------------------------------------------------------


def _mk_item(asset: str, when: datetime) -> NewsItem:
    return NewsItem(
        asset_id=asset,
        published_at=when,
        source="test",
        headline=f"{asset} @ {when}",
    )


def test_filter_window_half_open() -> None:
    start = datetime(2024, 6, 4, tzinfo=UTC)
    end = datetime(2024, 6, 6, tzinfo=UTC)
    items = [
        _mk_item("A", datetime(2024, 6, 3, 23, tzinfo=UTC)),  # before start -> out
        _mk_item("B", datetime(2024, 6, 4, 0, tzinfo=UTC)),  # == start -> in
        _mk_item("C", datetime(2024, 6, 5, 12, tzinfo=UTC)),  # inside -> in
        _mk_item("D", datetime(2024, 6, 6, 0, tzinfo=UTC)),  # == end -> out (half-open)
    ]
    kept = filter_window(items, start, end)
    assert [it.asset_id for it in kept] == ["B", "C"]


def test_filter_window_empty_when_no_coverage() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 2, tzinfo=UTC)
    items = [_mk_item("A", datetime(2024, 6, 3, tzinfo=UTC))]
    assert filter_window(items, start, end) == []


# ---------------------------------------------------------------------------
# FixtureNewsProvider — packaged samples
# ---------------------------------------------------------------------------


def test_fixture_provider_returns_samples_for_requested_symbols() -> None:
    provider = FixtureNewsProvider()
    start = datetime(2024, 6, 3, tzinfo=UTC)
    end = datetime(2024, 6, 8, tzinfo=UTC)
    items = provider.fetch(["NVDA", "AMD"], start, end)
    symbols = {it.asset_id for it in items}
    assert symbols == {"NVDA", "AMD"}
    assert all(it.source == "fixture" for it in items)
    # 3 NVDA + 3 AMD in the packaged samples within this window.
    assert len(items) == 6


def test_fixture_provider_filters_by_symbol_case_insensitive() -> None:
    provider = FixtureNewsProvider()
    start = datetime(2024, 6, 3, tzinfo=UTC)
    end = datetime(2024, 6, 8, tzinfo=UTC)
    assert {it.asset_id for it in provider.fetch(["nvda"], start, end)} == {"NVDA"}


def test_fixture_provider_applies_window() -> None:
    provider = FixtureNewsProvider()
    # [2024-06-04, 2024-06-06): NVDA samples at 06-03 13:30, 06-04 14:00, 06-06 16:45.
    # Only 06-04 14:00 falls in the half-open window.
    start = datetime(2024, 6, 4, tzinfo=UTC)
    end = datetime(2024, 6, 6, tzinfo=UTC)
    items = provider.fetch(["NVDA"], start, end)
    assert len(items) == 1
    assert items[0].headline == "NVDA hits fresh high on data-center demand"


def test_fixture_provider_uncovered_symbol_returns_empty() -> None:
    provider = FixtureNewsProvider()
    start = datetime(2024, 6, 3, tzinfo=UTC)
    end = datetime(2024, 6, 8, tzinfo=UTC)
    assert provider.fetch(["TSLA"], start, end) == []


def test_fixture_provider_accepts_custom_samples() -> None:
    custom = [
        _mk_item("FOO", datetime(2024, 1, 1, tzinfo=UTC)),
    ]
    provider = FixtureNewsProvider(samples=custom)
    items = provider.fetch(
        ["FOO"], datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)
    )
    assert len(items) == 1
    assert items[0].asset_id == "FOO"


# ---------------------------------------------------------------------------
# YfinanceNewsProvider — field conversion + window + cap (no network)
# ---------------------------------------------------------------------------


def _yf_raw(symbol: str, when: datetime, title: str = "stub") -> dict[str, Any]:
    """One yfinance-native news dict with an epoch publish time."""
    return {
        "title": title,
        "publisher": "Reuters",
        "link": f"https://example.com/{symbol}",
        "providerPublishTime": int(when.timestamp()),
        "type": "STORY",
        "relatedTickers": [symbol],
    }


def _install_fake_yfinance(
    monkeypatch: pytest.MonkeyPatch,
    feeds: dict[str, list[dict[str, Any]]] | None = None,
    raiser: dict[str, type[Exception]] | None = None,
) -> dict[str, list[dict[str, object]]]:
    """Inject a fake ``yfinance`` module; return a captured-calls map."""
    captured: dict[str, list[dict[str, object]]] = {}

    class _FakeTicker:
        def __init__(self, symbol: str) -> None:
            self._symbol = symbol

        @property
        def news(self) -> list[dict[str, Any]]:
            symbol = self._symbol
            exc = raiser.get(symbol) if raiser else None
            if exc is not None:
                raise exc("simulated network failure")
            feed = (feeds or {}).get(symbol, [])
            captured.setdefault(symbol, []).append({"called": True})
            return feed

    fake_yf = SimpleNamespace(Ticker=_FakeTicker)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    return captured


def test_yfinance_fetch_maps_fields_and_window(monkeypatch: pytest.MonkeyPatch) -> None:
    in_window = datetime(2024, 6, 4, 14, 0, tzinfo=UTC)
    out_before = datetime(2024, 6, 2, 14, 0, tzinfo=UTC)
    out_at_end = datetime(2024, 6, 6, 0, 0, tzinfo=UTC)
    _install_fake_yfinance(
        monkeypatch,
        feeds={
            "NVDA": [
                _yf_raw("NVDA", in_window, title="NVDA surges on earnings"),
                _yf_raw("NVDA", out_before, title="NVDA old news"),
                _yf_raw("NVDA", out_at_end, title="NVDA at end"),
            ]
        },
    )
    provider = YfinanceNewsProvider(max_items_per_asset=100)
    items = provider.fetch(
        ["NVDA"],
        datetime(2024, 6, 3, tzinfo=UTC),
        datetime(2024, 6, 6, tzinfo=UTC),
    )
    assert len(items) == 1
    it = items[0]
    assert it.asset_id == "NVDA"
    assert it.source == "yfinance"
    assert it.headline == "NVDA surges on earnings"
    assert it.published_at == in_window
    assert it.url == "https://example.com/NVDA"
    assert it.params["publisher"] == "Reuters"
    assert it.params["raw"]["title"] == "NVDA surges on earnings"


def test_yfinance_fetch_caps_per_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    feed = [
        _yf_raw("NVDA", datetime(2024, 6, 3, 10 + i, 0, tzinfo=UTC), title=f"NVDA item {i}")
        for i in range(5)
    ]
    _install_fake_yfinance(monkeypatch, feeds={"NVDA": feed})
    provider = YfinanceNewsProvider(max_items_per_asset=2)
    items = provider.fetch(
        ["NVDA"],
        datetime(2024, 6, 1, tzinfo=UTC),
        datetime(2024, 6, 10, tzinfo=UTC),
    )
    assert len(items) == 2
    assert [it.headline for it in items] == ["NVDA item 0", "NVDA item 1"]


def test_yfinance_fetch_empty_feed_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_yfinance(monkeypatch, feeds={"NVDA": []})
    provider = YfinanceNewsProvider()
    items = provider.fetch(
        ["NVDA"],
        datetime(2024, 6, 1, tzinfo=UTC),
        datetime(2024, 6, 10, tzinfo=UTC),
    )
    assert items == []


def test_yfinance_fetch_skips_unparseable_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    good = _yf_raw("NVDA", datetime(2024, 6, 4, 14, 0, tzinfo=UTC), title="good")
    bad = {"title": "bad", "publisher": "x", "link": None, "providerPublishTime": "not-a-date"}
    _install_fake_yfinance(monkeypatch, feeds={"NVDA": [bad, good]})
    provider = YfinanceNewsProvider()
    items = provider.fetch(
        ["NVDA"],
        datetime(2024, 6, 1, tzinfo=UTC),
        datetime(2024, 6, 10, tzinfo=UTC),
    )
    assert len(items) == 1
    assert items[0].headline == "good"


def test_yfinance_fetch_continues_past_symbol_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_yfinance(
        monkeypatch,
        feeds={"AMD": [_yf_raw("AMD", datetime(2024, 6, 4, 14, 0, tzinfo=UTC), title="AMD news")]},
        raiser={"NVDA": ConnectionError},
    )
    provider = YfinanceNewsProvider()
    items = provider.fetch(
        ["NVDA", "AMD"],
        datetime(2024, 6, 1, tzinfo=UTC),
        datetime(2024, 6, 10, tzinfo=UTC),
    )
    # NVDA raised (exhausted retries) but AMD still came through.
    assert len(items) == 1
    assert items[0].asset_id == "AMD"


def test_yfinance_fetch_skips_empty_headline(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _yf_raw("NVDA", datetime(2024, 6, 4, 14, 0, tzinfo=UTC), title="   ")
    _install_fake_yfinance(monkeypatch, feeds={"NVDA": [raw]})
    provider = YfinanceNewsProvider()
    items = provider.fetch(
        ["NVDA"],
        datetime(2024, 6, 1, tzinfo=UTC),
        datetime(2024, 6, 10, tzinfo=UTC),
    )
    assert items == []


# ---------------------------------------------------------------------------
# runtime_checkable — both providers satisfy NewsProvider
# ---------------------------------------------------------------------------


def test_providers_are_runtime_checkable_newsprovider() -> None:
    assert isinstance(FixtureNewsProvider(), NewsProvider)
    assert isinstance(YfinanceNewsProvider(), NewsProvider)
