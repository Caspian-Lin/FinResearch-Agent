"""Pure-unit tests for the Moving Average Crossover strategy (FRA-30).

No DB — the strategy is a pure function of a price wide-frame; we feed
synthetic frames (tz-aware UTC midnight index, deterministic values) and assert
both the raw ``weights`` output and the end-to-end ``run_backtest`` outcome.

关键防前视口径:策略**不**自行 shift(遵守 FRA-28 反双重滞后契约);均线用含
当前日收盘的 SMA,防前视由引擎 ``holdings = decision.shift(1)`` 兑现(t 日信号
t+1 执行)。覆盖:

1. 金叉/死叉信号正确(上升 → 逐日金叉做多;下降 → 始终死叉空仓)。
2. 窗口不足(前 slow-1 行)→ 空仓。
3. 单资产金叉满仓、死叉空仓;多资产等权分配 / 单资产做多。
4. 参数(fast/slow)可配;fast>=slow / 非正 → ValueError。
5. 防前视:改动未来行价格不影响已生成的历史信号。
6. 反双重滞后:金叉信号 t 日产生,t+1 日才进持仓(engine shift)。
7. 协议 isinstance;shape 一致。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest
from app.services.backtest.engine import run_backtest
from app.services.backtest.protocols import Strategy
from app.services.backtest.strategies import MACrossoverStrategy
from app.services.backtest.types import BacktestConfig, RebalanceFreq

# ---------------------------------------------------------------------------
# helpers / fixtures
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
        "strategy_name": "ma_crossover",
        "initial_capital": 100_000.0,
        "cost_bps": 0.0,
        "rebalance": RebalanceFreq.DAILY,
    }
    fields.update(overrides)
    return BacktestConfig(**fields)


ASSET_A = "A"
ASSET_B = "B"

# 6 个交易日的确定性序列。RAMP_UP 单调升(fast 会穿上穿 slow → 金叉);
# RAMP_DOWN 单调降(fast 始终 < slow → 死叉)。
DAYS6 = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]
RAMP_UP = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
RAMP_DOWN = [15.0, 14.0, 13.0, 12.0, 11.0, 10.0]


def _single_frame(series: list[float], asset_id: str = ASSET_A) -> pd.DataFrame:
    return _prices({d: [p] for d, p in zip(DAYS6, series, strict=True)}, [asset_id])


# ---------------------------------------------------------------------------
# 1) golden / death cross signal
# ---------------------------------------------------------------------------


def test_golden_cross_on_uptrend_single_asset() -> None:
    # fast=2, slow=3,单调升:前 2 行窗口不足 → 0;t2 起 fast>slow → 满仓(1)。
    prices = _single_frame(RAMP_UP)
    target = MACrossoverStrategy(fast=2, slow=3).weights(prices)
    # 手算:fast_ma(2)=[NaN,10.5,11.5,12.5,13.5,14.5],slow_ma(3)=[NaN,NaN,11,12,13,14]
    # fast>slow: [F, F, T, T, T, T] → 单资产等权/1 = [0,0,1,1,1,1]。
    expected = pd.Series([0.0, 0.0, 1.0, 1.0, 1.0, 1.0], index=prices.index, name=ASSET_A)
    pd.testing.assert_series_equal(target[ASSET_A], expected, check_names=False)


def test_death_cross_on_downtrend_stays_cash() -> None:
    # 单调降:fast 始终 < slow → 全空仓。
    prices = _single_frame(RAMP_DOWN)
    target = MACrossoverStrategy(fast=2, slow=3).weights(prices)
    assert (target[ASSET_A].to_numpy() == 0.0).all()


# ---------------------------------------------------------------------------
# 2) insufficient window → cash
# ---------------------------------------------------------------------------


def test_insufficient_window_is_cash() -> None:
    # slow=3 → 前 2 行(slow-1)均线为 NaN → signal 0(空仓)。
    prices = _single_frame(RAMP_UP)
    target = MACrossoverStrategy(fast=2, slow=3).weights(prices)
    assert target[ASSET_A].iloc[0] == pytest.approx(0.0)
    assert target[ASSET_A].iloc[1] == pytest.approx(0.0)


def test_longer_slow_window_delays_first_signal() -> None:
    # fast=3, slow=5:前 4 行窗口不足;t4(第 5 行)起金叉。
    series = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
    days = [
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
        "2024-01-05",
        "2024-01-08",
        "2024-01-09",
        "2024-01-10",
    ]
    prices = _prices({d: [p] for d, p in zip(days, series, strict=True)}, [ASSET_A])
    target = MACrossoverStrategy(fast=3, slow=5).weights(prices)
    # fast_ma(3)=[NaN,NaN,11,12,13,14,15]; slow_ma(5)=[NaN×4,12,13,14]
    # fast>slow: t4(13>12)起 True → [0,0,0,0,1,1,1]。
    expected = pd.Series([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0], index=prices.index)
    pd.testing.assert_series_equal(target[ASSET_A], expected, check_names=False)


# ---------------------------------------------------------------------------
# 3) multi-asset equal-weight allocation
# ---------------------------------------------------------------------------


def test_multi_asset_equal_weight_when_both_golden() -> None:
    # 两资产都单调升 → 都金叉 → 等权 [0.5, 0.5]。
    prices = _prices(
        {d: [p, p] for d, p in zip(DAYS6, RAMP_UP, strict=True)},
        [ASSET_A, ASSET_B],
    )
    target = MACrossoverStrategy(fast=2, slow=3).weights(prices)
    # 前 2 行窗口不足 → [0,0];t2 起等权。
    for ts in [_ts("2024-01-02"), _ts("2024-01-03")]:
        assert target.loc[ts, ASSET_A] == pytest.approx(0.0)
        assert target.loc[ts, ASSET_B] == pytest.approx(0.0)
    for ts in [_ts("2024-01-04"), _ts("2024-01-08"), _ts("2024-01-09")]:
        assert target.loc[ts, ASSET_A] == pytest.approx(0.5)
        assert target.loc[ts, ASSET_B] == pytest.approx(0.5)
    # 做多行权重和 == 1。
    assert np.allclose(target.iloc[2:].sum(axis=1).to_numpy(), 1.0)


def test_multi_asset_only_long_asset_gets_full_weight() -> None:
    # A 单调升(金叉)、B 单调降(死叉)→ 只做多 A,等权/1 = 全仓 A。
    prices = _prices(
        {d: [a, b] for d, a, b in zip(DAYS6, RAMP_UP, RAMP_DOWN, strict=True)},
        [ASSET_A, ASSET_B],
    )
    target = MACrossoverStrategy(fast=2, slow=3).weights(prices)
    # t2 起:A 金叉做多(1)、B 死叉空仓(0)。
    for ts in [_ts("2024-01-04"), _ts("2024-01-08"), _ts("2024-01-09")]:
        assert target.loc[ts, ASSET_A] == pytest.approx(1.0)
        assert target.loc[ts, ASSET_B] == pytest.approx(0.0)
    # 全死叉不可能(至少 A 金叉)→ 不存在全现金日(t2 起)。
    assert np.allclose(target.iloc[2:].sum(axis=1).to_numpy(), 1.0)


def test_all_death_cross_universe_is_cash() -> None:
    # 两资产都单调降 → 全死叉 → 全现金。
    prices = _prices(
        {d: [p, p] for d, p in zip(DAYS6, RAMP_DOWN, strict=True)},
        [ASSET_A, ASSET_B],
    )
    target = MACrossoverStrategy(fast=2, slow=3).weights(prices)
    assert (target.to_numpy() == 0.0).all()


# ---------------------------------------------------------------------------
# 4) parameter validation
# ---------------------------------------------------------------------------


def test_fast_must_be_strictly_less_than_slow() -> None:
    with pytest.raises(ValueError, match="strictly less"):
        MACrossoverStrategy(fast=5, slow=5)
    with pytest.raises(ValueError, match="strictly less"):
        MACrossoverStrategy(fast=10, slow=5)


def test_periods_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        MACrossoverStrategy(fast=0, slow=5)
    with pytest.raises(ValueError, match="positive"):
        MACrossoverStrategy(fast=2, slow=-1)


def test_default_parameters_are_sane() -> None:
    # 默认 fast=5, slow=20 应可构造且满足协议。
    strat = MACrossoverStrategy()
    assert strat is not None
    assert isinstance(strat, Strategy)


# ---------------------------------------------------------------------------
# 5) anti-look-ahead — future prices must not move past signals
# ---------------------------------------------------------------------------


def test_future_price_does_not_move_past_signals() -> None:
    # 仅改最后一天(t5):base 收 15,var 收 5(把 t5 从金叉打成死叉)。
    # signal[t] 只用 ≤t 数据 → t5 的改动不影响 weights[0..4]。
    base = _single_frame(RAMP_UP)  # [10,11,12,13,14,15]
    var_series = RAMP_UP[:-1] + [5.0]  # [10,11,12,13,14,5]
    var = _single_frame(var_series)

    w_base = MACrossoverStrategy(fast=2, slow=3).weights(base)
    w_var = MACrossoverStrategy(fast=2, slow=3).weights(var)

    # weights[0..4] 完全相同(t5 不影响 ≤t4 的信号)。
    pd.testing.assert_series_equal(
        w_base[ASSET_A].iloc[:5], w_var[ASSET_A].iloc[:5], check_names=False
    )
    # weights[5] 应不同:base 金叉(1)、var 死叉(0)。
    # base: fast_ma(2)[5]=14.5 > slow_ma(3)[5]=14 → 1
    # var:  fast_ma(2)[5]=mean(14,5)=9.5 < slow_ma(3)[5]=mean(13,14,5)=10.67 → 0
    assert w_base[ASSET_A].iloc[5] == pytest.approx(1.0)
    assert w_var[ASSET_A].iloc[5] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 6) anti-double-lag — signal at t moves holding at t+1, not t
# ---------------------------------------------------------------------------


def test_signal_at_t_moves_holding_at_t_plus_one() -> None:
    # fast=2,slow=3 单调升:weights=[0,0,1,1,1,1]。
    # holdings = weights.shift(1).fillna(0) = [0,0,0,1,1,1]。
    # → 金叉信号在 t2(2024-01-04)产生,但 t2 持仓仍 0,t3(2024-01-05)才满仓。
    prices = _single_frame(RAMP_UP)
    res = run_backtest(prices, MACrossoverStrategy(fast=2, slow=3), _config())
    holdings = res.positions

    t2 = _ts("2024-01-04")  # 金叉信号产生日(weights[t2]=1)
    t3 = _ts("2024-01-05")  # 信号生效日(holdings[t3]=weights[t2]=1)
    assert holdings.loc[t2, ASSET_A] == pytest.approx(0.0)  # 信号日尚未持仓
    assert holdings.loc[t3, ASSET_A] == pytest.approx(1.0)  # 次日才满仓(T+1)
    # turnover 只在进/出场日出现:进场一次(t3: 0→1 = 1.0);之后持有 → 0。
    assert res.turnover.sum() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 7) protocol + shape + end-to-end
# ---------------------------------------------------------------------------


def test_satisfies_strategy_protocol_and_shape() -> None:
    prices = _single_frame(RAMP_UP)
    strat = MACrossoverStrategy(fast=2, slow=3)
    assert isinstance(strat, Strategy)
    target = strat.weights(prices)
    assert target.shape == prices.shape
    assert list(target.index) == list(prices.index)
    assert list(target.columns) == list(prices.columns)
    # 策略不自行 shift:输出的是决策日权重(非整体后移)。
    assert not target.iloc[0].isna().any()
    # 权重和 ∈ [0, 1](做空不支持,无负权重)。
    row_sums = target.sum(axis=1)
    assert (row_sums >= -1e-9).all()
    assert (row_sums <= 1.0 + 1e-9).all()


def test_end_to_end_engine_produces_result() -> None:
    # 端到端:金叉后持有,equity 跟随上涨;产生 equity/returns/turnover。
    prices = _single_frame(RAMP_UP)
    res = run_backtest(prices, MACrossoverStrategy(fast=2, slow=3), _config())
    # 末值应高于初始(金叉段 A 上涨 12→15,净涨)。
    assert res.equity_curve.iloc[-1] > res.equity_curve.iloc[0]
    # 首日全现金(shift),equity == initial。
    assert res.equity_curve.iloc[0] == 100_000.0
    assert res.daily_returns.iloc[0] == 0.0
    # 指标尚未计算(留给 risk-metrics issue)。
    assert res.metrics is None
