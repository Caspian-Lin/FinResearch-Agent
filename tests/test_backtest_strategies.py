"""Pure-unit tests for the baseline strategies (FRA-29).

No DB — strategies are pure functions of a price wide-frame; we feed synthetic
frames (tz-aware UTC midnight index, deterministic values) and assert both the
raw ``weights`` output and the end-to-end ``run_backtest`` outcome. Coverage:

1. Buy&Hold 单资产无成本 → equity 精确等于 (1+ret).cumprod()*initial(== 价格 cumret)。
2. Buy&Hold 多资产等权 → target 恒定 [0.5,0.5];turnover 仅首日建仓一次。
3. Buy&Hold 自定义初始权重 → target 恒为该权重;和可 < 1(现金补足)。
4. Buy&Hold 剔除整列全缺资产;全缺 universe → 全现金。
5. Equal Weight 固定 universe → target 恒等权;单资产 → 全仓。
6. Equal Weight 动态 universe(资产陆续上市)→ target 扩容、纳入日产生换手。
7. Equal Weight 剔除全缺;全缺 → 全现金。
8. 两策略满足 ``Strategy`` 协议(isinstance);不自行 shift(首行非 NaN、shape 一致)。
9. 固定 universe 下 B&H 等权 ≡ Equal Weight(engine target-weight 框架特性)。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest
from app.services.backtest.engine import run_backtest
from app.services.backtest.protocols import Strategy
from app.services.backtest.strategies import BuyAndHoldStrategy, EqualWeightStrategy
from app.services.backtest.types import BacktestConfig, RebalanceFreq

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
        "strategy_name": "baseline",
        "initial_capital": 100_000.0,
        "cost_bps": 0.0,
        "rebalance": RebalanceFreq.DAILY,
    }
    fields.update(overrides)
    return BacktestConfig(**fields)


ASSET_A = "A"
ASSET_B = "B"

# An 8-day ramp 100 → 109 (deterministic, non-flat). Two columns: A is the ramp,
# B is a flat series so multi-asset tests can reuse the same fixture.
RAMP_DAYS: dict[str, list[float]] = {
    "2024-01-02": [100.0, 100.0],
    "2024-01-03": [101.0, 100.0],
    "2024-01-04": [103.0, 100.0],
    "2024-01-05": [102.0, 100.0],  # small drawdown day
    "2024-01-08": [105.0, 100.0],
    "2024-01-09": [107.0, 100.0],
    "2024-01-10": [106.0, 100.0],  # drawdown
    "2024-01-11": [109.0, 100.0],
}


# ---------------------------------------------------------------------------
# 1) Buy & Hold single asset — equity == price cumret
# ---------------------------------------------------------------------------


def test_buy_hold_single_asset_matches_cumret() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A])
    res = run_backtest(prices, BuyAndHoldStrategy(), _config())

    expected = (1.0 + prices[ASSET_A].pct_change().fillna(0.0)).cumprod() * 100_000.0
    pd.testing.assert_series_equal(res.equity_curve, expected.rename("equity"), check_names=False)
    assert res.equity_curve.iloc[0] == 100_000.0
    assert res.daily_returns.iloc[0] == 0.0


# ---------------------------------------------------------------------------
# 2) Buy & Hold equal-weight — constant target, turnover only at first rebalance
# ---------------------------------------------------------------------------


def test_buy_hold_equal_weight_target_constant() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    target = BuyAndHoldStrategy().weights(prices)
    # 每行恒为 [0.5, 0.5],权重和 == 1。
    assert target[ASSET_A].eq(0.5).all()
    assert target[ASSET_B].eq(0.5).all()
    assert np.allclose(target.sum(axis=1).to_numpy(), 1.0)


def test_buy_hold_equal_weight_turnover_only_initial_rebalance() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    res = run_backtest(prices, BuyAndHoldStrategy(), _config(universe=(ASSET_A, ASSET_B)))
    # holdings = target.shift(1).fillna(0):首日全现金;[t1] 起恒 [0.5,0.5]。
    holdings = res.positions
    assert holdings.iloc[0][ASSET_A] == pytest.approx(0.0)
    assert holdings.iloc[0][ASSET_B] == pytest.approx(0.0)
    assert holdings.iloc[1][ASSET_A] == pytest.approx(0.5)
    assert holdings.iloc[1][ASSET_B] == pytest.approx(0.5)
    assert holdings.iloc[2:][ASSET_A].eq(0.5).all()
    assert holdings.iloc[2:][ASSET_B].eq(0.5).all()
    # 换手仅在首日建仓出现一次(0→[0.5,0.5] = 1.0),持有期恒定 → 0。
    nonzero = (res.turnover > 1e-12).sum()
    assert int(nonzero) == 1
    assert res.turnover.sum() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 3) Buy & Hold custom initial weights
# ---------------------------------------------------------------------------


def test_buy_hold_custom_weights() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    strat = BuyAndHoldStrategy(weights={ASSET_A: 0.7, ASSET_B: 0.3})
    target = strat.weights(prices)
    assert target[ASSET_A].eq(0.7).all()
    assert target[ASSET_B].eq(0.3).all()
    assert np.allclose(target.sum(axis=1).to_numpy(), 1.0)


def test_buy_hold_custom_weights_allow_cash_remainder() -> None:
    # 权重和 < 1 → 余额为现金(引擎不强制满仓)。
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    target = BuyAndHoldStrategy(weights={ASSET_A: 0.4, ASSET_B: 0.1}).weights(prices)
    assert target[ASSET_A].eq(0.4).all()
    assert target[ASSET_B].eq(0.1).all()
    assert np.allclose(target.sum(axis=1).to_numpy(), 0.5)


def test_buy_hold_custom_weights_missing_asset_is_zero() -> None:
    # weights 未给 B → B 视作 0(只有 A 建仓)。
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    target = BuyAndHoldStrategy(weights={ASSET_A: 1.0}).weights(prices)
    assert target[ASSET_A].eq(1.0).all()
    assert target[ASSET_B].eq(0.0).all()


# ---------------------------------------------------------------------------
# 4) Buy & Hold drops all-NaN column; all-NaN universe → cash
# ---------------------------------------------------------------------------


def test_buy_hold_drops_all_nan_column() -> None:
    # B 整列 NaN(从未上市)→ 剔除,仅 A 等权 = 全仓 A。
    days = sorted(RAMP_DAYS)
    a_seq = [v[0] for v in RAMP_DAYS.values()]
    prices = _prices(
        {d: [a, float("nan")] for d, a in zip(days, a_seq, strict=True)},
        [ASSET_A, ASSET_B],
    )
    target = BuyAndHoldStrategy().weights(prices)
    assert target[ASSET_A].eq(1.0).all()
    assert target[ASSET_B].eq(0.0).all()


def test_buy_hold_all_nan_universe_is_cash() -> None:
    days = sorted(RAMP_DAYS)
    prices = _prices(
        {d: [float("nan"), float("nan")] for d in days},
        [ASSET_A, ASSET_B],
    )
    target = BuyAndHoldStrategy().weights(prices)
    assert (target.to_numpy() == 0.0).all()


# ---------------------------------------------------------------------------
# 5) Equal Weight — fixed universe constant; single asset full weight
# ---------------------------------------------------------------------------


def test_equal_weight_fixed_universe_constant() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    target = EqualWeightStrategy().weights(prices)
    # 两资产首日即有效 → 每行 [0.5, 0.5]。
    assert target[ASSET_A].eq(0.5).all()
    assert target[ASSET_B].eq(0.5).all()
    assert np.allclose(target.sum(axis=1).to_numpy(), 1.0)


def test_equal_weight_single_asset_full_weight() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A])
    target = EqualWeightStrategy().weights(prices)
    assert target[ASSET_A].eq(1.0).all()


# ---------------------------------------------------------------------------
# 6) Equal Weight dynamic universe — listing expands, turnover on inclusion
# ---------------------------------------------------------------------------


def test_equal_weight_dynamic_universe_target_and_turnover() -> None:
    # A 全期有效;B 从第 3 行(2024-01-05)起才有效 = 后上市。
    days = sorted(RAMP_DAYS)
    a_seq = [v[0] for v in RAMP_DAYS.values()]
    # 前 3 行(01-02/03/04)B 为 NaN → 01-05 起上市(days sorted 索引 3 = 01-05)。
    b_prices = [float("nan"), float("nan"), float("nan"), 100.0, 100.0, 100.0, 100.0, 100.0]
    prices = _prices(
        {d: [a, b] for d, a, b in zip(days, a_seq, b_prices, strict=True)},
        [ASSET_A, ASSET_B],
    )

    target = EqualWeightStrategy().weights(prices)
    # B 上市前(01-02、01-03、01-04):仅 A → target=[1, 0]。
    pre = [_ts("2024-01-02"), _ts("2024-01-03"), _ts("2024-01-04")]
    for ts in pre:
        assert target.loc[ts, ASSET_A] == pytest.approx(1.0)
        assert target.loc[ts, ASSET_B] == pytest.approx(0.0)
    # B 上市后(01-05 起):target=[0.5, 0.5]。
    for ts in [_ts("2024-01-05"), _ts("2024-01-08"), _ts("2024-01-11")]:
        assert target.loc[ts, ASSET_A] == pytest.approx(0.5)
        assert target.loc[ts, ASSET_B] == pytest.approx(0.5)

    # 跑引擎(DAILY):纳入 B 的决策(01-05)shift 到 01-08 生效 → 01-08 产生换手。
    res = run_backtest(prices, EqualWeightStrategy(), _config(universe=(ASSET_A, ASSET_B)))
    # holdings = target.shift(1).fillna(0):
    #   01-02 = [0,0]; 01-03 = target[01-02]=[1,0]; 01-04=[1,0]; 01-05=[1,0];
    #   01-08 = target[01-05]=[0.5,0.5]  ← 纳入 B 生效
    # turnover: 01-03 = 1.0(建仓 A); 01-08 = |0.5-1|+|0.5-0| = 1.0(纳入 B)。
    assert res.turnover.loc[_ts("2024-01-03")] == pytest.approx(1.0)
    assert res.turnover.loc[_ts("2024-01-08")] == pytest.approx(1.0)
    # 仅这两处换手;持有期 turnover == 0。
    nonzero_days = res.turnover[res.turnover > 1e-12].index
    assert set(nonzero_days) == {_ts("2024-01-03"), _ts("2024-01-08")}


# ---------------------------------------------------------------------------
# 7) Equal Weight drops all-NaN; all-NaN → cash
# ---------------------------------------------------------------------------


def test_equal_weight_drops_all_nan_column() -> None:
    days = sorted(RAMP_DAYS)
    a_seq = [v[0] for v in RAMP_DAYS.values()]
    prices = _prices(
        {d: [a, float("nan")] for d, a in zip(days, a_seq, strict=True)},
        [ASSET_A, ASSET_B],
    )
    target = EqualWeightStrategy().weights(prices)
    # B 全缺恒 0;A 是唯一上市资产 → 全仓。
    assert target[ASSET_A].eq(1.0).all()
    assert target[ASSET_B].eq(0.0).all()


def test_equal_weight_all_nan_universe_is_cash() -> None:
    days = sorted(RAMP_DAYS)
    prices = _prices(
        {d: [float("nan"), float("nan")] for d in days},
        [ASSET_A, ASSET_B],
    )
    target = EqualWeightStrategy().weights(prices)
    assert (target.to_numpy() == 0.0).all()


# ---------------------------------------------------------------------------
# 8) Protocol satisfaction + no self-shift (anti-double-lag contract)
# ---------------------------------------------------------------------------


def test_buy_hold_satisfies_strategy_protocol() -> None:
    assert isinstance(BuyAndHoldStrategy(), Strategy)


def test_equal_weight_satisfies_strategy_protocol() -> None:
    assert isinstance(EqualWeightStrategy(), Strategy)


def test_strategies_do_not_shift_and_shape_matches() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    for strategy in (BuyAndHoldStrategy(), EqualWeightStrategy()):
        target = strategy.weights(prices)
        # 输出与输入同形状、同 index/columns。
        assert target.shape == prices.shape
        assert list(target.index) == list(prices.index)
        assert list(target.columns) == list(prices.columns)
        # 策略不自行 shift:首行必须有明确权重(非 NaN)。
        assert not target.iloc[0].isna().any()
        # 每行权重和 ∈ [0, 1](现金补足)。
        row_sums = target.sum(axis=1)
        assert (row_sums >= -1e-9).all()
        assert (row_sums <= 1.0 + 1e-9).all()


# ---------------------------------------------------------------------------
# 9) Fixed-universe equivalence — B&H equal-weight ≡ Equal Weight
# ---------------------------------------------------------------------------


def test_buy_hold_equal_weight_equals_equal_weight_fixed_universe() -> None:
    # 固定 universe(所有资产首日即上市)下,B&H 等权与 Equal Weight 的目标权重
    # 完全相同 —— 这是 engine target-weight 框架的特性(恒权重收益不模拟漂移)。
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])
    bh = BuyAndHoldStrategy().weights(prices)
    ew = EqualWeightStrategy().weights(prices)
    pd.testing.assert_frame_equal(bh, ew)
