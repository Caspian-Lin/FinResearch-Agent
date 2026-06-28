"""AkShare full-market universe fetcher tests (FRA-79).

The fetchers (:mod:`app.services.datasources.akshare_universe`) each wrap one
AkShare endpoint and normalize its raw Chinese-named DataFrame into the
unified exchange-suffix :class:`AssetSpec` form. AkShare is mocked out by
injecting a fake module into ``sys.modules`` — no network, no real library —
returning hand-built DataFrames in each endpoint's *actual* column shape
(verified against akshare 1.18.64). This exercises the real normalization
(code-prefix → exchange/suffix, list_status tagging) for every market plus
the pure helpers.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest
from app.services.datasources.akshare_universe import (
    AssetSpec,
    _a_share_exchange,
    _normalize_a_share_code,
    _parse_us_code,
    fetch_a_share_universe,
    fetch_all_universes,
    fetch_delisted_a_shares,
    fetch_hk_universe,
    fetch_us_universe,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_a_share_exchange_first_digit_routes_to_exchange() -> None:
    # SSE: main board 60xxxx + STAR 688xxx.
    assert _a_share_exchange("600519") == ("SSE", ".SH")
    assert _a_share_exchange("688981") == ("SSE", ".SH")
    # SZSE: main 00xxxx + ChiNext 30xxxx.
    assert _a_share_exchange("000001") == ("SZSE", ".SZ")
    assert _a_share_exchange("300750") == ("SZSE", ".SZ")
    # BSE: 4xxxxx / 8xxxxx.
    assert _a_share_exchange("430047") == ("BSE", ".BJ")
    assert _a_share_exchange("830799") == ("BSE", ".BJ")


def test_a_share_exchange_unknown_prefix_raises() -> None:
    # '5' is funds/ETFs, not a modeled A-share code block.
    with pytest.raises(ValueError, match="A-share code prefix"):
        _a_share_exchange("500000")


def test_normalize_a_share_code_pads_and_trims() -> None:
    assert _normalize_a_share_code("600519") == "600519"
    assert _normalize_a_share_code(" 600519 ") == "600519"
    # AkShare occasionally returns codes as ints; coerce + zero-pad to 6.
    assert _normalize_a_share_code(600519) == "600519"


def test_parse_us_code_known_prefixes() -> None:
    assert _parse_us_code("105.AAPL") == ("105", "AAPL")  # NASDAQ
    assert _parse_us_code("106.JPM") == ("106", "JPM")  # NYSE
    assert _parse_us_code("153.SPY") == ("153", "SPY")  # AMEX


def test_parse_us_code_unknown_returns_none() -> None:
    # Unknown numeric prefix and bare (dot-less) tickers are skipped upstream.
    assert _parse_us_code("999.JUNK") is None
    assert _parse_us_code("bareticker") is None


# ---------------------------------------------------------------------------
# Fetchers — akshare mocked at sys.modules
# ---------------------------------------------------------------------------


def _install_akshare(monkeypatch: pytest.MonkeyPatch, **funcs: object) -> None:
    """Inject a fake ``akshare`` module exposing the named endpoint stubs."""
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(**funcs))


def test_fetch_a_share_universe_normalizes_to_unified_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_akshare(
        monkeypatch,
        stock_info_a_code_name=lambda: pd.DataFrame(
            {"code": ["600519", "000001", "430047"], "name": ["贵州茅台", "平安银行", "诺思兰德"]}
        ),
    )
    specs = fetch_a_share_universe()
    assert specs == [
        AssetSpec("600519.SH", "SSE", "贵州茅台", "stock", "CNY", "akshare", "active"),
        AssetSpec("000001.SZ", "SZSE", "平安银行", "stock", "CNY", "akshare", "active"),
        AssetSpec("430047.BJ", "BSE", "诺思兰德", "stock", "CNY", "akshare", "active"),
    ]


def test_fetch_hk_universe_keeps_five_digit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_akshare(
        monkeypatch,
        stock_hk_spot_em=lambda: pd.DataFrame(
            {"代码": ["00700", "02272"], "名称": ["腾讯控股", "科拓股份"]}
        ),
    )
    specs = fetch_hk_universe()
    assert specs == [
        AssetSpec("00700.HK", "HKEX", "腾讯控股", "stock", "HKD", "yfinance", "active"),
        AssetSpec("02272.HK", "HKEX", "科拓股份", "stock", "HKD", "yfinance", "active"),
    ]


def test_fetch_us_universe_maps_prefix_and_skips_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_akshare(
        monkeypatch,
        stock_us_spot_em=lambda: pd.DataFrame(
            {
                "代码": ["105.AAPL", "106.JPM", "153.SPY", "999.JUNK"],
                "名称": ["Apple Inc", "JPMorgan", "SPDR S&P 500", "Unknown"],
            }
        ),
    )
    specs = fetch_us_universe()
    # The unknown '999.' prefix is dropped, not raised on.
    assert specs == [
        AssetSpec("AAPL.O", "NASDAQ", "Apple Inc", "stock", "USD", "yfinance", "active"),
        AssetSpec("JPM.N", "NYSE", "JPMorgan", "stock", "USD", "yfinance", "active"),
        AssetSpec("SPY.A", "AMEX", "SPDR S&P 500", "stock", "USD", "yfinance", "active"),
    ]


def test_fetch_delisted_a_shares_tags_delisted_across_both_boards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Note the deliberately different column names: SZ uses 证券代码/证券简称,
    # SH uses 公司代码/公司简称 — a real AkShare quirk the fetcher must handle.
    _install_akshare(
        monkeypatch,
        stock_info_sz_delist=lambda symbol: pd.DataFrame(
            {"证券代码": ["000003"], "证券简称": ["PT金田Ａ"]}
        ),
        stock_info_sh_delist=lambda: pd.DataFrame(
            {"公司代码": ["600001"], "公司简称": ["邯郸钢铁"]}
        ),
    )
    specs = fetch_delisted_a_shares()
    assert specs == [
        AssetSpec("000003.SZ", "SZSE", "PT金田Ａ", "stock", "CNY", "akshare", "delisted"),
        AssetSpec("600001.SH", "SSE", "邯郸钢铁", "stock", "CNY", "akshare", "delisted"),
    ]


def test_fetch_all_universes_splits_active_and_delisted(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_akshare(
        monkeypatch,
        stock_info_a_code_name=lambda: pd.DataFrame({"code": ["600519"], "name": ["贵州茅台"]}),
        stock_hk_spot_em=lambda: pd.DataFrame({"代码": ["00700"], "名称": ["腾讯控股"]}),
        stock_us_spot_em=lambda: pd.DataFrame({"代码": ["105.AAPL"], "名称": ["Apple Inc"]}),
        stock_info_sz_delist=lambda symbol: pd.DataFrame(
            {"证券代码": ["000003"], "证券简称": ["PT金田Ａ"]}
        ),
        stock_info_sh_delist=lambda: pd.DataFrame(
            {"公司代码": ["600001"], "公司简称": ["邯郸钢铁"]}
        ),
    )
    active, delisted = fetch_all_universes()

    assert len(active) == 3  # 1 A-share + 1 HK + 1 US
    assert all(s.list_status == "active" for s in active)
    # Active spans all three markets / data sources.
    assert {s.exchange for s in active} == {"SSE", "HKEX", "NASDAQ"}

    assert len(delisted) == 2  # 1 SZ + 1 SH delisted
    assert all(s.list_status == "delisted" for s in delisted)
