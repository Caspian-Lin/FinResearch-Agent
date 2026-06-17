"""Pure-unit tests for the benchmark comparison service (FRA-33).

No DB — ``compute_benchmark_comparison`` 是纯函数;我们喂给它合成价格宽表
(tz-aware UTC 午夜 index,确定性数值)与一个 ``BacktestResult`` 桩(只需
``config.initial_capital`` / ``equity_curve`` / ``daily_returns``),断言:

1. 基准 equity 精确等于 ``(1+ret).cumprod() * initial``;首日 == initial_capital。
2. 对齐:策略 index ⊃ 基准时,基准缺失日 ffill 沿用前值。
3. drawdown = ``equity / cummax - 1``:回撤日 <0、创新高日 ==0;基准前缀 NaN 段保持 NaN。
4. excess_returns = ``strategy_daily_returns - benchmark_daily_returns``(逐日)。
5. 基准完全不覆盖策略区间 → ``ValueError``。
6. QQQ / SPY 参数化:compute 与 symbol 无关,只看传入的 prices。
7. ``load_benchmark_prices`` 的 DB 依赖用一个最小 stub 验证 happy-path(空返回 → ValueError)。

模仿 ``tests/test_backtest_engine.py`` / ``tests/test_backtest_strategies.py`` 的
``_ts`` / ``_prices`` / ``_config`` helpers 与 RAMP 风格。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import pytest
from app.services.backtest.benchmark import (
    BenchmarkComparison,
    compute_benchmark_comparison,
)
from app.services.backtest.types import BacktestConfig, BacktestResult, RebalanceFreq

# ---------------------------------------------------------------------------
# helpers / fixtures (self-contained, mirrors tests/test_backtest_engine.py)
# ---------------------------------------------------------------------------


def _ts(day: str) -> pd.Timestamp:
    """A tz-aware UTC-midnight timestamp (matches the wide-frame convention)."""
    return pd.Timestamp(datetime.fromisoformat(f"{day}T00:00:00"), tz="UTC")


def _prices(
    day_prices: dict[str, list[float]],
    asset_ids: list[str],
) -> pd.DataFrame:
    """Build a synthetic price wide-frame.

    ``day_prices`` maps ISO date → per-asset price list (aligned with ``asset_ids``).
    """
    days = sorted(day_prices)
    index = pd.DatetimeIndex([_ts(d) for d in days])
    data = {aid: [day_prices[d][i] for d in days] for i, aid in enumerate(asset_ids)}
    return pd.DataFrame(data, index=index, columns=asset_ids).astype("float64")


def _config(**overrides: Any) -> BacktestConfig:
    fields: dict[str, Any] = {
        "universe": ("A",),
        "start": date(2024, 1, 2),
        "end": date(2024, 1, 12),
        "strategy_name": "stub",
        "initial_capital": 100_000.0,
        "cost_bps": 0.0,
        "rebalance": RebalanceFreq.DAILY,
    }
    fields.update(overrides)
    return BacktestConfig(**fields)


def _result(
    equity: pd.Series,
    daily_returns: pd.Series,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """构造最小 ``BacktestResult`` 桩(benchmark 计算只看 config/equity/returns)。"""
    if config is None:
        config = _config()
    # turnover / positions 形状对齐 equity.index,benchmark 计算不读它们。
    turnover = pd.Series(0.0, index=equity.index, name="turnover")
    positions = pd.DataFrame(0.0, index=equity.index, columns=list(config.universe))
    return BacktestResult(
        config=config,
        equity_curve=equity,
        daily_returns=daily_returns,
        turnover=turnover,
        positions=positions,
        trades=[],
        metrics=None,
    )


ASSET_A = "A"
BENCH = "QQQ"

# 8 策略交易日 ramp 100 → 109(确定性,非平坦)。基准 QQQ 用同长度但不同数值的 ramp。
STRAT_DAYS: dict[str, list[float]] = {
    "2024-01-02": [100.0],
    "2024-01-03": [101.0],
    "2024-01-04": [103.0],
    "2024-01-05": [102.0],  # 策略小回撤日
    "2024-01-08": [105.0],
    "2024-01-09": [107.0],
    "2024-01-10": [106.0],  # 策略回撤日
    "2024-01-11": [109.0],
}

# 基准 QQQ 价格(同窗口,不同走势,便于断言 excess ≠ 0)。
QQQ_DAYS: dict[str, list[float]] = {
    "2024-01-02": [200.0],
    "2024-01-03": [202.0],
    "2024-01-04": [201.0],
    "2024-01-05": [204.0],
    "2024-01-08": [206.0],
    "2024-01-09": [205.0],  # 基准回撤日
    "2024-01-10": [208.0],
    "2024-01-11": [210.0],
}


def _strategy_result_from_prices(prices: pd.DataFrame) -> BacktestResult:
    """把合成价格当作 buy & hold,得到一个等价 ``BacktestResult``(供 benchmark 对比)。"""
    p = prices.iloc[:, 0]
    ret = p.pct_change().fillna(0.0)
    equity = (1.0 + ret).cumprod() * 100_000.0
    equity.iloc[0] = 100_000.0
    equity = equity.rename("equity")
    ret = ret.rename("returns")
    return _result(equity, ret)


# ---------------------------------------------------------------------------
# 1) benchmark equity == (1+ret).cumprod()*initial; first day == initial
# ---------------------------------------------------------------------------


def test_benchmark_equity_matches_cumprod_and_first_day() -> None:
    strat_prices = _prices(STRAT_DAYS, [ASSET_A])
    strat_res = _strategy_result_from_prices(strat_prices)

    bench_prices = _prices(QQQ_DAYS, [BENCH])
    cmp = compute_benchmark_comparison(strat_res, bench_prices)

    q = bench_prices[BENCH]
    expected_ret = q.pct_change().fillna(0.0)
    expected_equity = (1.0 + expected_ret).cumprod() * 100_000.0
    expected_equity.iloc[0] = 100_000.0

    pd.testing.assert_series_equal(
        cmp.benchmark_equity.rename("eq"),
        expected_equity.rename("eq"),
        check_names=False,
    )
    # 首日精确等于 initial_capital。
    assert cmp.benchmark_equity.iloc[0] == 100_000.0


# ---------------------------------------------------------------------------
# 2) alignment — strategy index ⊃ benchmark; ffill on missing benchmark days
# ---------------------------------------------------------------------------


def test_alignment_benchmark_missing_days_ffill() -> None:
    # 策略 index 有 8 天;基准只给其中部分日子,缺日应 ffill 沿用前值。
    strat_prices = _prices(STRAT_DAYS, [ASSET_A])
    strat_res = _strategy_result_from_prices(strat_prices)

    # 基准只给 01-02、01-04、01-11 三个点(其余策略交易日缺)。
    sparse_bench = _prices(
        {
            "2024-01-02": [200.0],
            "2024-01-04": [204.0],
            "2024-01-11": [210.0],
        },
        [BENCH],
    )
    cmp = compute_benchmark_comparison(strat_res, sparse_bench)

    q = sparse_bench[BENCH]
    expected_ret = q.pct_change().fillna(0.0)
    expected_equity = (1.0 + expected_ret).cumprod() * 100_000.0
    expected_equity.iloc[0] = 100_000.0
    # reindex 到策略 index + ffill。
    expected_aligned = expected_equity.reindex(strat_prices.index).ffill()

    pd.testing.assert_series_equal(
        cmp.benchmark_equity.rename("eq"),
        expected_aligned.rename("eq"),
        check_names=False,
    )
    # 01-03 策略有但基准无 → 沿用 01-02 的基准净值(= 100_000,首日 0 收益)。
    assert cmp.benchmark_equity.loc[_ts("2024-01-03")] == pytest.approx(100_000.0)
    # 01-05 ~ 01-10 策略有但基准无 → 沿用 01-04 的基准净值。
    eq_0104 = cmp.benchmark_equity.loc[_ts("2024-01-04")]
    for d in ("2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10"):
        assert cmp.benchmark_equity.loc[_ts(d)] == pytest.approx(eq_0104)


def test_alignment_prefix_nan_preserved_when_no_prior_benchmark() -> None:
    # 基准在策略窗口前缀段(01-02、01-03、01-04)无数据,01-05 起才有 → 前缀段
    # 无前值可 ffill,保持 NaN;01-05 起有效。
    strat_prices = _prices(STRAT_DAYS, [ASSET_A])
    strat_res = _strategy_result_from_prices(strat_prices)

    late_bench = _prices(
        {
            "2024-01-05": [204.0],
            "2024-01-08": [206.0],
            "2024-01-09": [205.0],
            "2024-01-10": [208.0],
            "2024-01-11": [210.0],
        },
        [BENCH],
    )
    cmp = compute_benchmark_comparison(strat_res, late_bench)

    # 前缀段(无前值)benchmark equity 为 NaN。
    for d in ("2024-01-02", "2024-01-03", "2024-01-04"):
        assert pd.isna(cmp.benchmark_equity.loc[_ts(d)])
    # 01-05 起有效(= initial_capital,首项 cumprod=1)。
    assert cmp.benchmark_equity.loc[_ts("2024-01-05")] == pytest.approx(100_000.0)
    # 但 01-05 之后缺失日(此处无)应 ffill —— 结构保证已被前测覆盖。


# ---------------------------------------------------------------------------
# 3) drawdown — equity/cummax - 1; benchmark prefix NaN stays NaN
# ---------------------------------------------------------------------------


def test_drawdown_strategy_and_benchmark_correctness() -> None:
    strat_prices = _prices(STRAT_DAYS, [ASSET_A])
    strat_res = _strategy_result_from_prices(strat_prices)
    bench_prices = _prices(QQQ_DAYS, [BENCH])
    cmp = compute_benchmark_comparison(strat_res, bench_prices)

    # 策略 drawdown:回撤日 <0、创新高日 ==0。
    s_dd = cmp.strategy_drawdown
    assert (s_dd.dropna() <= 1e-9).all()
    # 01-05:策略价 102 < 前高 103 → 回撤 <0。
    assert s_dd.loc[_ts("2024-01-05")] < 0.0
    # 01-08:策略价 105 创新高 → drawdown ==0。
    assert s_dd.loc[_ts("2024-01-08")] == pytest.approx(0.0)

    # 基准 drawdown 与独立计算一致。
    q = bench_prices[BENCH]
    bench_equity = (1.0 + q.pct_change().fillna(0.0)).cumprod() * 100_000.0
    bench_equity.iloc[0] = 100_000.0
    expected_bench_dd = bench_equity / bench_equity.cummax() - 1.0
    expected_bench_dd = expected_bench_dd.reindex(strat_prices.index)
    pd.testing.assert_series_equal(
        cmp.benchmark_drawdown.rename("dd"),
        expected_bench_dd.rename("dd"),
        check_names=False,
    )
    # 基准 01-09 价 205 < 前高 206 → 回撤 <0。
    assert cmp.benchmark_drawdown.loc[_ts("2024-01-09")] < 0.0


def test_drawdown_prefix_nan_preserved() -> None:
    # 基准前缀段无数据 → cummax 仍 NaN → drawdown 保持 NaN(不强行补 0)。
    strat_prices = _prices(STRAT_DAYS, [ASSET_A])
    strat_res = _strategy_result_from_prices(strat_prices)
    late_bench = _prices(
        {
            "2024-01-05": [204.0],
            "2024-01-11": [210.0],
        },
        [BENCH],
    )
    cmp = compute_benchmark_comparison(strat_res, late_bench)
    for d in ("2024-01-02", "2024-01-03", "2024-01-04"):
        assert pd.isna(cmp.benchmark_drawdown.loc[_ts(d)])
    # 01-05 起有效(首项为峰 → drawdown ==0)。
    assert cmp.benchmark_drawdown.loc[_ts("2024-01-05")] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 4) excess_returns = strategy_daily_returns - benchmark_daily_returns
# ---------------------------------------------------------------------------


def test_excess_returns_equals_strategy_minus_benchmark() -> None:
    strat_prices = _prices(STRAT_DAYS, [ASSET_A])
    strat_res = _strategy_result_from_prices(strat_prices)
    bench_prices = _prices(QQQ_DAYS, [BENCH])
    cmp = compute_benchmark_comparison(strat_res, bench_prices)

    q = bench_prices[BENCH]
    bench_ret = q.pct_change().fillna(0.0).reindex(strat_prices.index)
    expected_excess = strat_res.daily_returns - bench_ret

    pd.testing.assert_series_equal(
        cmp.excess_returns.rename("ex"),
        expected_excess.rename("ex"),
        check_names=False,
    )
    # 至少一天超额 ≠ 0(策略与基准走势不同)。
    assert (cmp.excess_returns.dropna().abs() > 1e-12).any()
    # 首日:策略 ret=0、基准 ret=0 → excess=0。
    assert cmp.excess_returns.iloc[0] == pytest.approx(0.0)


def test_excess_returns_prefix_nan_when_no_prior_benchmark() -> None:
    strat_prices = _prices(STRAT_DAYS, [ASSET_A])
    strat_res = _strategy_result_from_prices(strat_prices)
    late_bench = _prices(
        {
            "2024-01-05": [204.0],
            "2024-01-11": [210.0],
        },
        [BENCH],
    )
    cmp = compute_benchmark_comparison(strat_res, late_bench)
    # 前缀段 benchmark ret 经 ffill 仍 NaN(无前值)→ excess 为 NaN。
    for d in ("2024-01-02", "2024-01-03", "2024-01-04"):
        assert pd.isna(cmp.excess_returns.loc[_ts(d)])


# ---------------------------------------------------------------------------
# 5) benchmark completely misses strategy window → ValueError
# ---------------------------------------------------------------------------


def test_benchmark_completely_missing_window_raises() -> None:
    strat_prices = _prices(STRAT_DAYS, [ASSET_A])
    strat_res = _strategy_result_from_prices(strat_prices)
    # 基准只在完全不相交的日期上有数据(策略窗口为 2024-01)。
    disjoint_bench = _prices(
        {
            "2024-02-05": [200.0],
            "2024-02-06": [201.0],
        },
        [BENCH],
    )
    with pytest.raises(ValueError, match="no price data overlapping"):
        compute_benchmark_comparison(strat_res, disjoint_bench)


def test_empty_benchmark_frame_raises() -> None:
    strat_prices = _prices(STRAT_DAYS, [ASSET_A])
    strat_res = _strategy_result_from_prices(strat_prices)
    empty = pd.DataFrame()
    with pytest.raises(ValueError, match="empty"):
        compute_benchmark_comparison(strat_res, empty)


# ---------------------------------------------------------------------------
# 6) QQQ / SPY parametrization — compute is symbol-agnostic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("symbol", ["QQQ", "SPY", "IWM"])
def test_compute_symbol_agnostic(symbol: str) -> None:
    strat_prices = _prices(STRAT_DAYS, [ASSET_A])
    strat_res = _strategy_result_from_prices(strat_prices)

    # 用同一组基准价格数值,只换列名 → equity/drawdown/excess 必须完全一致。
    bench_qqq = _prices(QQQ_DAYS, ["QQQ"])
    bench_other = _prices(QQQ_DAYS, [symbol])

    cmp_q = compute_benchmark_comparison(strat_res, bench_qqq)
    cmp_o = compute_benchmark_comparison(strat_res, bench_other)

    pd.testing.assert_series_equal(
        cmp_q.benchmark_equity.rename("x"), cmp_o.benchmark_equity.rename("x"), check_names=False
    )
    pd.testing.assert_series_equal(
        cmp_q.benchmark_drawdown.rename("x"),
        cmp_o.benchmark_drawdown.rename("x"),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        cmp_q.excess_returns.rename("x"), cmp_o.excess_returns.rename("x"), check_names=False
    )


# ---------------------------------------------------------------------------
# 7) load_benchmark_prices — DB stub (happy path) + empty → ValueError
# ---------------------------------------------------------------------------


class _StubDB:
    """Minimal Session stub: 只记录调用,不真正查 DB。"""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []


def test_load_benchmark_prices_returns_load_prices_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """load_benchmark_prices 透传 load_prices 的返回(非空),签名匹配。"""
    import app.services.backtest.benchmark as bm

    sentinel = _prices({"2024-01-02": [200.0], "2024-01-03": [201.0]}, ["QQQ"])
    captured: dict[str, Any] = {}

    def fake_load_prices(**kwargs: Any) -> pd.DataFrame:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(bm, "load_prices", fake_load_prices)

    import uuid

    aid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    db = _StubDB()  # type: ignore[arg-type]
    out = bm.load_benchmark_prices(
        db=db,
        benchmark_asset_id=aid,
        start=date(2024, 1, 2),
        end=date(2024, 1, 3),
        price_field=bm.PriceField.ADJUSTED,
    )
    pd.testing.assert_frame_equal(out, sentinel)
    # 透传给 load_prices 的参数正确(universe 为单元素元组)。
    assert captured["universe"] == (aid,)
    assert captured["source"] == "yfinance"
    assert captured["start"] == date(2024, 1, 2)
    assert captured["end"] == date(2024, 1, 3)
    assert captured["price_field"] is bm.PriceField.ADJUSTED


def test_load_benchmark_prices_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.backtest.benchmark as bm

    def fake_load_prices(**kwargs: Any) -> pd.DataFrame:
        return pd.DataFrame()

    monkeypatch.setattr(bm, "load_prices", fake_load_prices)

    import uuid

    with pytest.raises(ValueError, match="no price data"):
        bm.load_benchmark_prices(
            db=_StubDB(),  # type: ignore[arg-type]
            benchmark_asset_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            start=date(2024, 1, 2),
            end=date(2024, 1, 3),
            price_field=bm.PriceField.ADJUSTED,
        )


# ---------------------------------------------------------------------------
# sanity — return type & all series aligned to strategy index
# ---------------------------------------------------------------------------


def test_all_series_aligned_to_strategy_index() -> None:
    strat_prices = _prices(STRAT_DAYS, [ASSET_A])
    strat_res = _strategy_result_from_prices(strat_prices)
    bench_prices = _prices(QQQ_DAYS, [BENCH])

    cmp = compute_benchmark_comparison(strat_res, bench_prices)

    assert isinstance(cmp, BenchmarkComparison)
    expected_index = strat_res.equity_curve.index
    for s in (
        cmp.strategy_equity,
        cmp.benchmark_equity,
        cmp.strategy_drawdown,
        cmp.benchmark_drawdown,
        cmp.excess_returns,
    ):
        assert s.index.equals(expected_index)
