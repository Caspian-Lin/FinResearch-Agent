"""Data-source adapter layer tests (FRA-23).

Covers the dispatcher (:func:`get_data_source` + :data:`SUPPORTED_SOURCES`),
the A-share symbol mapping for each domestic adapter, and the
``AkshareSource`` / ``TushareSource`` field-conversion paths.

akshare/tushare are *optional* dependencies and are not installed in CI, so the
adapters' lazy ``import akshare``/``import tushare`` is intercepted by injecting
a fake module into ``sys.modules`` — no network, no real library. The fake
returns a hand-built DataFrame in the source's native column shape so the
adapter's column mapping + UTC normalization + symbol mapping are exercised for
real.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from app.services.datasources import (
    SUPPORTED_SOURCES,
    AkshareSource,
    TushareSource,
    YfinanceSource,
    get_data_source,
)
from app.services.datasources.akshare import _map_a_share_symbol
from app.services.datasources.tushare import _map_tushare_symbol

# ---------------------------------------------------------------------------
# Dispatcher + SUPPORTED_SOURCES
# ---------------------------------------------------------------------------


def test_supported_sources_lists_all_three() -> None:
    assert SUPPORTED_SOURCES == ("yfinance", "akshare", "tushare")


def test_get_data_source_routes_known_sources() -> None:
    yf = get_data_source("yfinance")
    ak = get_data_source("akshare")
    assert isinstance(yf, YfinanceSource)
    assert isinstance(ak, AkshareSource)
    assert yf.name == "yfinance"
    assert ak.name == "akshare"


def test_get_data_source_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unsupported source"):
        get_data_source("bloomberg")


def test_get_data_source_tushare_routes_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.datasources as ds_mod

    monkeypatch.setattr(ds_mod, "settings", SimpleNamespace(tushare_token="fake-token"))
    ts = get_data_source("tushare")
    assert isinstance(ts, TushareSource)
    assert ts.name == "tushare"


def test_get_data_source_tushare_without_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.datasources as ds_mod

    monkeypatch.setattr(ds_mod, "settings", SimpleNamespace(tushare_token=""))
    with pytest.raises(ValueError, match="TUSHARE_TOKEN"):
        get_data_source("tushare")


# ---------------------------------------------------------------------------
# A-share symbol mapping
# ---------------------------------------------------------------------------


def test_map_a_share_symbol_ss_to_sh_prefix() -> None:
    assert _map_a_share_symbol("600519.SS") == "sh600519"
    assert _map_a_share_symbol("000001.SZ") == "sz000001"


def test_map_a_share_symbol_rejects_non_a_share() -> None:
    with pytest.raises(ValueError, match="A-shares only"):
        _map_a_share_symbol("AAPL")


def test_map_tushare_symbol_ss_to_sh_suffix() -> None:
    assert _map_tushare_symbol("600519.SS") == "600519.SH"
    assert _map_tushare_symbol("000001.SZ") == "000001.SZ"


def test_map_tushare_symbol_rejects_non_a_share() -> None:
    with pytest.raises(ValueError, match="A-shares only"):
        _map_tushare_symbol("SPY")


# ---------------------------------------------------------------------------
# AkshareSource — field conversion + symbol mapping + empty/non-a-share
# ---------------------------------------------------------------------------


def _akshare_df() -> pd.DataFrame:
    """A frame shaped like ``ak.stock_zh_a_hist`` (Chinese column names)."""
    return pd.DataFrame(
        [
            {
                "日期": "2024-01-02",
                "开盘": 100.0,
                "收盘": 100.5,
                "最高": 101.0,
                "最低": 99.0,
                "成交量": 1000,
            },
            {
                "日期": "2024-01-03",
                "开盘": 100.5,
                "收盘": 101.5,
                "最高": 102.0,
                "最低": 100.0,
                "成交量": 1100,
            },
        ]
    )


def test_akshare_fetch_maps_chinese_columns_and_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _stock_zh_a_hist(**kwargs: object) -> pd.DataFrame:
        captured.update(kwargs)
        return _akshare_df()

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist=_stock_zh_a_hist))

    bars = AkshareSource().fetch_ohlcv(
        "600519.SS", datetime(2024, 1, 1).date(), datetime(2024, 1, 5).date()
    )

    # the adapter mapped .SS → sh prefix and passed qfq adjustment + YYYYMMDD dates
    assert captured["symbol"] == "sh600519"
    assert captured["adjust"] == "qfq"
    assert captured["start_date"] == "20240101"
    assert captured["end_date"] == "20240105"

    assert len(bars) == 2
    b0, b1 = bars
    assert b0.time == datetime(2024, 1, 2, tzinfo=UTC)
    assert b0.close == Decimal("100.5")
    assert b0.adjusted_close == Decimal("100.5")  # qfq single-regime: adjusted == close
    assert b0.open == Decimal("100.0")
    assert b0.high == Decimal("101.0")
    assert b0.low == Decimal("99.0")
    assert b0.volume == 1000
    assert b1.time == datetime(2024, 1, 3, tzinfo=UTC)


def test_akshare_fetch_empty_frame_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist=lambda **kw: pd.DataFrame())
    )
    bars = AkshareSource().fetch_ohlcv(
        "600519.SS", datetime(2024, 1, 1).date(), datetime(2024, 1, 5).date()
    )
    assert bars == []


def test_akshare_fetch_non_a_share_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist=lambda **kw: _akshare_df())
    )
    with pytest.raises(ValueError, match="A-shares only"):
        AkshareSource().fetch_ohlcv(
            "AAPL", datetime(2024, 1, 1).date(), datetime(2024, 1, 5).date()
        )


def test_akshare_handles_opening_price_variant_column(monkeypatch: pytest.MonkeyPatch) -> None:
    """Column wording drift (开盘 vs 开盘价) is tolerated by the candidate map."""
    df = pd.DataFrame(
        [
            {
                "日期": "2024-01-02",
                "开盘价": 100.0,
                "收盘价": 100.5,
                "最高价": 101.0,
                "最低价": 99.0,
                "成交量": 1000,
            }
        ]
    )
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist=lambda **kw: df))
    bars = AkshareSource().fetch_ohlcv(
        "000001.SZ", datetime(2024, 1, 1).date(), datetime(2024, 1, 5).date()
    )
    assert len(bars) == 1
    assert bars[0].open == Decimal("100.0")
    assert bars[0].close == Decimal("100.5")


# ---------------------------------------------------------------------------
# TushareSource — token gating + pro.daily field conversion + symbol mapping
# ---------------------------------------------------------------------------


class _FakeProApi:
    """Stand-in for the Tushare ``pro`` client returned by ``ts.pro_api()``."""

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df
        self.calls: list[dict[str, object]] = []

    def daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(kwargs)
        return self.df


def _install_fake_tushare(monkeypatch: pytest.MonkeyPatch, df: pd.DataFrame) -> _FakeProApi:
    """Inject a fake ``tushare`` module; return its pro client for assertions."""
    pro = _FakeProApi(df)
    fake_ts = SimpleNamespace(
        set_token=lambda token: None,
        pro_api=lambda: pro,
    )
    monkeypatch.setitem(sys.modules, "tushare", fake_ts)
    return pro


def test_tushare_source_without_token_raises() -> None:
    with pytest.raises(ValueError, match="TUSHARE_TOKEN"):
        TushareSource(token="")


def test_tushare_fetch_maps_pro_daily_and_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    # pro.daily returns newest-first; verify the adapter sorts ascending.
    df = pd.DataFrame(
        [
            {
                "ts_code": "600519.SH",
                "trade_date": "20240103",
                "open": 100.5,
                "high": 102.0,
                "low": 100.0,
                "close": 101.5,
                "vol": 1100,
            },
            {
                "ts_code": "600519.SH",
                "trade_date": "20240102",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "vol": 1000,
            },
        ]
    )
    pro = _install_fake_tushare(monkeypatch, df)

    bars = TushareSource(token="fake-token").fetch_ohlcv(
        "600519.SS", datetime(2024, 1, 1).date(), datetime(2024, 1, 5).date()
    )

    # the adapter mapped .SS → .SH and passed YYYYMMDD date bounds
    assert pro.calls[0]["ts_code"] == "600519.SH"
    assert pro.calls[0]["start_date"] == "20240101"
    assert pro.calls[0]["end_date"] == "20240105"

    assert len(bars) == 2
    assert bars[0].time == datetime(2024, 1, 2, tzinfo=UTC)  # sorted ascending
    assert bars[0].close == Decimal("100.5")
    assert bars[0].adjusted_close is None  # pro.daily is unadjusted
    assert bars[0].open == Decimal("100.0")
    assert bars[0].high == Decimal("101.0")
    assert bars[0].low == Decimal("99.0")
    assert bars[0].volume == 1000
    assert bars[1].time == datetime(2024, 1, 3, tzinfo=UTC)
    assert bars[1].close == Decimal("101.5")


def test_tushare_fetch_empty_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_tushare(monkeypatch, pd.DataFrame())
    bars = TushareSource(token="fake-token").fetch_ohlcv(
        "600519.SS", datetime(2024, 1, 1).date(), datetime(2024, 1, 5).date()
    )
    assert bars == []


def test_tushare_fetch_non_a_share_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_tushare(monkeypatch, pd.DataFrame())
    with pytest.raises(ValueError, match="A-shares only"):
        TushareSource(token="fake-token").fetch_ohlcv(
            "SPY", datetime(2024, 1, 1).date(), datetime(2024, 1, 5).date()
        )


# ---------------------------------------------------------------------------
# YfinanceSource — pure delegation wrapper (FRA-23)
# ---------------------------------------------------------------------------


def test_yfinance_source_delegates_to_fetch_ohlcv(monkeypatch: pytest.MonkeyPatch) -> None:
    """The adapter is a thin wrapper; it forwards (symbol, start, end, retryer)."""
    captured: dict[str, object] = {}

    def _fake_fetch(symbol: str, start: object, end: object, retryer: object = None) -> list:
        captured.update(symbol=symbol, start=start, end=end, retryer=retryer)
        return []

    # The wrapper resolves _yf_fetch_ohlcv from the package namespace at call
    # time, so patching it there (not the original app.services.yfinance module)
    # is what intercepts the delegation.
    import app.services.datasources as ds_mod

    monkeypatch.setattr(ds_mod, "_yf_fetch_ohlcv", _fake_fetch)

    YfinanceSource().fetch_ohlcv("AAPL", datetime(2024, 1, 1).date(), datetime(2024, 1, 5).date())

    assert captured["symbol"] == "AAPL"
    assert captured["start"] == datetime(2024, 1, 1).date()
    assert captured["end"] == datetime(2024, 1, 5).date()
