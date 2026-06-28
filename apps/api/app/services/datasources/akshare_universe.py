"""AkShare full-market universe fetchers (FRA-79).

Dynamic asset-list ingestion for the three markets the project tracks —
A-shares (SSE/SZSE/BSE), HK (HKEX), US (NASDAQ/NYSE/AMEX) — plus the
listing-lifecycle "delisted" boards. This replaces FRA-21's hard-coded ~48-row
``UNIVERSE`` with a live pull so newly listed and delisted instruments are
picked up on each seed run instead of requiring a code change.

Each fetcher wraps one AkShare "spot / list" endpoint, normalizes the raw
Chinese-named :class:`~pandas.DataFrame` into the project's unified
exchange-suffix symbol convention (FRA-78: ``600519.SH`` / ``02272.HK`` /
``SDOT.O``), and returns :class:`AssetSpec` rows ready for the upsert seeder.
AkShare is imported lazily inside each fetcher (same pattern as the OHLCV
adapter in :mod:`.akshare`), so this module imports without the optional
dependency installed — only an actual sync needs it.

Listing state
-------------
* ``stock_info_a_code_name`` / ``stock_hk_spot_em`` / ``stock_us_spot_em`` →
  the live tradable universe, ``list_status='active'``.
* ``stock_info_sz_delist`` / ``stock_info_sh_delist`` → terminated listings,
  ``list_status='delisted'``. They are returned separately so the seeder can
  upsert them *after* the active universe, letting ``delisted`` win on a
  ``(symbol, exchange)`` conflict (a code on both the live board and the
  delisted board ends up delisted) while still keeping the row — historical
  OHLCV and watchlist references survive.

The AkShare column names and code shapes below were verified against
akshare 1.18.64; the fetchers tolerate the small wording drift the library
is known for by reading the documented column rather than positional index.

Symbol normalization reference (FRA-78)
---------------------------------------
* A-share first-digit rule — ``6``/``9``→``.SH``, ``0``/``2``/``3``→``.SZ``,
  ``4``/``8``→``.BJ``.
* US AkShare ``代码`` is shaped ``105.SDOT``; the numeric prefix encodes the
  exchange: ``105``→``.O`` (NASDAQ), ``106``→``.N`` (NYSE), ``153``→``.A``
  (AMEX). Unknown prefixes are skipped rather than aborting the whole sync.

``asset_type`` is currently coarse-grained to ``stock`` for all three
markets; ETF/index/warrant classification from name keywords is a later
enhancement and not part of this issue.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# A-share first digit → (exchange, suffix). Covers SSE main board (60xxxx) and
# STAR (688xxx), SSE B-shares (9xxxxx); SZSE main (00xxxx) / ChiNext (30xxxx) /
# B-shares (20xxxx); BSE / NEEQ (4xxxxx, 8xxxxx).
_A_SHARE_PREFIX: dict[str, tuple[str, str]] = {
    "6": ("SSE", ".SH"),
    "9": ("SSE", ".SH"),  # SSE B-shares
    "0": ("SZSE", ".SZ"),
    "2": ("SZSE", ".SZ"),  # SZSE B-shares
    "3": ("SZSE", ".SZ"),  # ChiNext
    "4": ("BSE", ".BJ"),
    "8": ("BSE", ".BJ"),
}

# US AkShare ``代码`` prefix → (exchange, suffix). The column is shaped
# ``105.SDOT``; the numeric prefix encodes the listing exchange.
_US_PREFIX: dict[str, tuple[str, str]] = {
    "105": ("NASDAQ", ".O"),
    "106": ("NYSE", ".N"),
    "153": ("AMEX", ".A"),
}


@dataclass(frozen=True)
class AssetSpec:
    """One normalized instrument row, ready for the upsert seeder.

    Mirrors the mutable ``Asset`` columns plus the listing lifecycle. The
    seeder converts these to ``pg_insert`` rows and upserts on
    ``(symbol, exchange)``.
    """

    symbol: str
    exchange: str
    name: str
    asset_type: str
    currency: str
    data_source: str
    list_status: str = "active"


def _a_share_exchange(code: str) -> tuple[str, str]:
    """Map a 6-digit A-share code to ``(exchange, suffix)`` by first digit.

    Raises :class:`ValueError` for an unrecognized prefix so a genuinely novel
    code block surfaces loudly rather than being silently miscategorized.
    """
    info = _A_SHARE_PREFIX.get(code[0])
    if info is None:
        raise ValueError(f"unrecognized A-share code prefix: {code!r}")
    return info


def _normalize_a_share_code(code: object) -> str:
    """Coerce a raw A-share code to a trimmed, zero-padded 6-digit string.

    AkShare occasionally returns codes as ints or with stray whitespace; this
    gives a stable key (e.g. ``600519``, ``000001``) before suffixing.
    """
    return str(code).strip().zfill(6)[:6]


def _parse_us_code(raw: str) -> tuple[str, str] | None:
    """Split an AkShare US ``代码`` (``105.SDOT``) into ``(prefix, ticker)``.

    Returns ``None`` when the prefix is unknown so the caller can skip the
    row rather than abort. The ticker keeps its original case, which is what
    yfinance and the unified convention expect.
    """
    prefix, sep, ticker = raw.partition(".")
    if not sep or not ticker or prefix not in _US_PREFIX:
        return None
    return (prefix, ticker)


def fetch_a_share_universe() -> list[AssetSpec]:
    """Pull the live A-share universe (SSE/SZSE/BSE) → active specs.

    Source: ``ak.stock_info_a_code_name()`` → ``['code', 'name']`` (~5.5k
    rows). Each 6-digit code is mapped to its exchange + suffix by first
    digit and emitted with ``data_source='akshare'``, ``currency='CNY'``.
    """
    import akshare as ak

    df: pd.DataFrame = ak.stock_info_a_code_name()
    specs: list[AssetSpec] = []
    for code, name in zip(df["code"].tolist(), df["name"].tolist(), strict=False):
        c = _normalize_a_share_code(code)
        exchange, suffix = _a_share_exchange(c)
        specs.append(
            AssetSpec(
                symbol=f"{c}{suffix}",
                exchange=exchange,
                name=str(name).strip(),
                asset_type="stock",
                currency="CNY",
                data_source="akshare",
                list_status="active",
            )
        )
    return specs


def fetch_hk_universe() -> list[AssetSpec]:
    """Pull the live HK universe (HKEX) → active specs.

    Source: ``ak.stock_hk_spot_em()`` → ``['序号', '代码', '名称', …]`` (~4.7k
    rows). The 5-digit ``代码`` (e.g. ``02272``) is suffixed with ``.HK``
    verbatim — FRA-78 stores HK codes 5-digit; yfinance's 4-digit form is
    derived on demand by :func:`app.services.datasources._map_yfinance_symbol`.
    """
    import akshare as ak

    df: pd.DataFrame = ak.stock_hk_spot_em()
    specs: list[AssetSpec] = []
    for code, name in zip(df["代码"].tolist(), df["名称"].tolist(), strict=False):
        c = str(code).strip()
        specs.append(
            AssetSpec(
                symbol=f"{c}.HK",
                exchange="HKEX",
                name=str(name).strip(),
                asset_type="stock",
                currency="HKD",
                data_source="yfinance",
                list_status="active",
            )
        )
    return specs


def fetch_us_universe() -> list[AssetSpec]:
    """Pull the live US universe (NASDAQ/NYSE/AMEX) → active specs.

    Source: ``ak.stock_us_spot_em()`` → ``['…', '名称', '代码']`` (~13.5k rows),
    where ``代码`` is shaped ``105.SDOT``. The numeric prefix selects the
    exchange + suffix; rows with an unrecognized prefix are skipped (the
    endpoint occasionally lists pink-sheet / OTC codes we don't model).
    """
    import akshare as ak

    df: pd.DataFrame = ak.stock_us_spot_em()
    specs: list[AssetSpec] = []
    for code, name in zip(df["代码"].tolist(), df["名称"].tolist(), strict=False):
        parsed = _parse_us_code(str(code).strip())
        if parsed is None:
            continue
        prefix, ticker = parsed
        exchange, suffix = _US_PREFIX[prefix]
        specs.append(
            AssetSpec(
                symbol=f"{ticker}{suffix}",
                exchange=exchange,
                name=str(name).strip(),
                asset_type="stock",
                currency="USD",
                data_source="yfinance",
                list_status="active",
            )
        )
    return specs


def fetch_delisted_a_shares() -> list[AssetSpec]:
    """Pull the terminated-listing A-share boards → delisted specs.

    Two endpoints with *different* column names (a recurring AkShare quirk):

    * ``ak.stock_info_sz_delist(symbol='终止上市公司')`` →
      ``['证券代码', '证券简称', …]`` (~200 rows).
    * ``ak.stock_info_sh_delist()`` → ``['公司代码', '公司简称', …]`` (~150 rows).

    Each code is normalized + suffixed exactly like the active A-share path;
    only ``list_status`` differs (``delisted``). Returned separately so the
    seeder can apply them after the active universe.
    """
    import akshare as ak

    specs: list[AssetSpec] = []
    # SZSE delisted board.
    df_sz: pd.DataFrame = ak.stock_info_sz_delist(symbol="终止上市公司")
    for code, name in zip(df_sz["证券代码"].tolist(), df_sz["证券简称"].tolist(), strict=False):
        c = _normalize_a_share_code(code)
        exchange, suffix = _a_share_exchange(c)
        specs.append(
            AssetSpec(
                symbol=f"{c}{suffix}",
                exchange=exchange,
                name=str(name).strip(),
                asset_type="stock",
                currency="CNY",
                data_source="akshare",
                list_status="delisted",
            )
        )
    # SSE delisted board (different column names).
    df_sh: pd.DataFrame = ak.stock_info_sh_delist()
    for code, name in zip(df_sh["公司代码"].tolist(), df_sh["公司简称"].tolist(), strict=False):
        c = _normalize_a_share_code(code)
        exchange, suffix = _a_share_exchange(c)
        specs.append(
            AssetSpec(
                symbol=f"{c}{suffix}",
                exchange=exchange,
                name=str(name).strip(),
                asset_type="stock",
                currency="CNY",
                data_source="akshare",
                list_status="delisted",
            )
        )
    return specs


def fetch_all_universes() -> tuple[list[AssetSpec], list[AssetSpec]]:
    """Pull every market; return ``(active_specs, delisted_specs)``.

    Active = A-shares + HK + US (all ``list_status='active'``). Delisted = the
    terminated A-share boards. The split exists so the seeder can upsert
    active first, then delisted — guaranteeing the delisted flag wins on a
    ``(symbol, exchange)`` conflict without a separate merge step here.
    """
    active: list[AssetSpec] = []
    active.extend(fetch_a_share_universe())
    active.extend(fetch_hk_universe())
    active.extend(fetch_us_universe())
    delisted = fetch_delisted_a_shares()
    return (active, delisted)
