"""Pure-unit tests for the Momentum strategy (FRA-31).

No DB — strategy is a pure function of a price wide-frame; synthetic frames
(tz-aware UTC midnight, deterministic values) assert both raw ``weights`` and
end-to-end ``run_backtest``. 防前视口径 B(同 FRA-30):策略不自行 shift,靠 engine
``holdings = decision.shift(1)`` 兑现。覆盖:

1. top-k 选动量最高资产;等权 1/k;窗口不足 → 空仓。
2. universe 不足 k → 取可用数(等权)。
3. 参数校验(lookback / top_k 非正)。
4. 防前视(改未来价不影响历史信号);反双重滞后(t 信号 t+1 持仓)。
5. 协议 isinstance + shape + 端到端 engine。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest
from app.services.backtest.engine import run_backtest
from app.services.backtest.protocols import Strategy
from app.services.backtest.strategies import MomentumStrategy
from app.services.backtest.types import BacktestConfig, RebalanceFreq


def _ts(day: str) -> pd.Timestamp:
    return pd.Timestamp(datetime.fromisoformat(f"{day}T00:00:00"), tz="UTC")


def _prices(day_prices: dict[str, list[float]], asset_ids: list[str]) -> pd.DataFrame:
    days = sorted(day_prices)
    index = pd.DatetimeIndex([_ts(d) for d in days])
    data = {aid: [day_prices[d][i] for d in days] for i, aid in enumerate(asset_ids)}
    return pd.DataFrame(data, index=index, columns=asset_ids).astype("float64")


def _config(**overrides: Any) -> BacktestConfig:
    fields: dict[str, Any] = {
        "universe": ("A",),
        "start": date(2024, 1, 2),
        "end": date(2024, 1, 12),
        "strategy_name": "momentum",
        "initial_capital": 100_000.0,
        "cost_bps": 0.0,
        "rebalance": RebalanceFreq.DAILY,
    }
    fields.update(overrides)
    return BacktestConfig(**fields)


ASSET_A = "A"
ASSET_B = "B"
ASSET_C = "C"

# 3 资产确定性趋势:A 涨(强动量)、B 平、C 跌(弱动量)。lookback=2 时 t2 起有动量。
TREND: dict[str, list[float]] = {
    "2024-01-02": [10.0, 10.0, 10.0],
    "2024-01-03": [11.0, 10.0, 9.0],
    "2024-01-04": [12.0, 10.0, 8.0],
    "2024-01-05": [13.0, 10.0, 7.0],
}


def _trend_frame() -> pd.DataFrame:
    return _prices(TREND, [ASSET_A, ASSET_B, ASSET_C])


# ---------------------------------------------------------------------------
# 1) top-k selection + equal weight + insufficient window
# ---------------------------------------------------------------------------


def test_top_k_selects_highest_momentum() -> None:
    # lookback=2, top_k=1:前 2 行窗口不足 → 空仓;t2 起 A 动量最高 → 全仓 A。
    target = MomentumStrategy(lookback=2, top_k=1).weights(_trend_frame())
    for ts in [_ts("2024-01-02"), _ts("2024-01-03")]:
        assert target.loc[ts].sum() == pytest.approx(0.0)  # 全现金
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        assert target.loc[ts, ASSET_A] == pytest.approx(1.0)
        assert target.loc[ts, ASSET_B] == pytest.approx(0.0)
        assert target.loc[ts, ASSET_C] == pytest.approx(0.0)


def test_top_k_equal_weight() -> None:
    # top_k=2:t2 起 A(0.2)、B(0.0) 为前 2 → 等权 0.5;C(-0.2) 不选。
    target = MomentumStrategy(lookback=2, top_k=2).weights(_trend_frame())
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        assert target.loc[ts, ASSET_A] == pytest.approx(0.5)
        assert target.loc[ts, ASSET_B] == pytest.approx(0.5)
        assert target.loc[ts, ASSET_C] == pytest.approx(0.0)
    assert np.allclose(target.iloc[2:].sum(axis=1).to_numpy(), 1.0)


def test_insufficient_lookback_is_cash() -> None:
    # lookback=2 → 前 2 行(01-02、01-03)pct_change 为 NaN → 全现金。
    target = MomentumStrategy(lookback=2, top_k=1).weights(_trend_frame())
    assert target.iloc[0].sum() == pytest.approx(0.0)
    assert target.iloc[1].sum() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 2) universe smaller than k → takes available
# ---------------------------------------------------------------------------


def test_universe_smaller_than_k_takes_all_equal_weight() -> None:
    # top_k=5 但只有 3 资产 → 全选,等权 1/3。
    target = MomentumStrategy(lookback=2, top_k=5).weights(_trend_frame())
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        for asset in (ASSET_A, ASSET_B, ASSET_C):
            assert target.loc[ts, asset] == pytest.approx(1.0 / 3)
    assert np.allclose(target.iloc[2:].sum(axis=1).to_numpy(), 1.0)


# ---------------------------------------------------------------------------
# 3) parameter validation
# ---------------------------------------------------------------------------


def test_lookback_must_be_positive() -> None:
    with pytest.raises(ValueError, match="lookback"):
        MomentumStrategy(lookback=0, top_k=1)
    with pytest.raises(ValueError, match="lookback"):
        MomentumStrategy(lookback=-2, top_k=1)


def test_top_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="top_k"):
        MomentumStrategy(lookback=2, top_k=0)
    with pytest.raises(ValueError, match="top_k"):
        MomentumStrategy(lookback=2, top_k=-1)


# ---------------------------------------------------------------------------
# 4) anti-look-ahead + anti-double-lag
# ---------------------------------------------------------------------------


def test_future_price_does_not_move_past_signals() -> None:
    # 改最后一天(01-05)C 暴涨:不影响 weights[0..2](含 01-04);01-05 选股翻转。
    base = _trend_frame()
    var = _prices(
        {
            "2024-01-02": [10.0, 10.0, 10.0],
            "2024-01-03": [11.0, 10.0, 9.0],
            "2024-01-04": [12.0, 10.0, 8.0],
            "2024-01-05": [13.0, 10.0, 70.0],  # C 反转:动量变最高
        },
        [ASSET_A, ASSET_B, ASSET_C],
    )
    w_base = MomentumStrategy(lookback=2, top_k=1).weights(base)
    w_var = MomentumStrategy(lookback=2, top_k=1).weights(var)
    # ≤01-04 的权重完全相同(01-05 不影响历史信号)。
    pd.testing.assert_frame_equal(w_base.iloc[:3], w_var.iloc[:3])
    # 01-05:base 选 A(var C 未涨);var 选 C(C 动量 70/9-1≈6.78 远超 A 的 0.18)。
    assert w_base.loc[_ts("2024-01-05"), ASSET_A] == pytest.approx(1.0)
    assert w_var.loc[_ts("2024-01-05"), ASSET_C] == pytest.approx(1.0)


def test_signal_at_t_moves_holding_at_t_plus_one() -> None:
    # weights=[0,0,A=1,A=1]; holdings=shift → t2(01-04)信号产生但持仓 0,t3(01-05)才满仓。
    res = run_backtest(
        _trend_frame(),
        MomentumStrategy(lookback=2, top_k=1),
        _config(universe=(ASSET_A, ASSET_B, ASSET_C)),
    )
    holdings = res.positions
    t2 = _ts("2024-01-04")  # 信号产生日
    t3 = _ts("2024-01-05")  # 信号生效日
    assert holdings.loc[t2, ASSET_A] == pytest.approx(0.0)
    assert holdings.loc[t3, ASSET_A] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 5) protocol + shape + end-to-end
# ---------------------------------------------------------------------------


def test_satisfies_strategy_protocol_and_shape() -> None:
    strat = MomentumStrategy(lookback=2, top_k=1)
    assert isinstance(strat, Strategy)
    prices = _trend_frame()
    target = strat.weights(prices)
    assert target.shape == prices.shape
    assert list(target.index) == list(prices.index)
    assert list(target.columns) == list(prices.columns)
    assert not target.iloc[0].isna().any()
    row_sums = target.sum(axis=1)
    assert (row_sums >= -1e-9).all()
    assert (row_sums <= 1.0 + 1e-9).all()


def test_end_to_end_engine_produces_result() -> None:
    # 选 A(涨)→ 持有段 equity 上涨。
    res = run_backtest(
        _trend_frame(),
        MomentumStrategy(lookback=2, top_k=1),
        _config(universe=(ASSET_A, ASSET_B, ASSET_C)),
    )
    assert res.equity_curve.iloc[-1] > res.equity_curve.iloc[0]
    assert res.equity_curve.iloc[0] == 100_000.0
    assert res.daily_returns.iloc[0] == 0.0
    assert res.metrics is None
