"""Pure-unit tests for the Reversal strategy (FRA-32) — Momentum 的对照组。

No DB;口径同 Momentum(策略不自行 shift,靠 engine shift 兑现)。覆盖:bottom-k
选动量最低、等权、窗口不足、universe<k、参数校验、防前视、反双重滞后、协议、
端到端;额外验证与 Momentum 的对称/选股互补性。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest
from app.services.backtest.engine import run_backtest
from app.services.backtest.protocols import Strategy
from app.services.backtest.strategies import MomentumStrategy, ReversalStrategy
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
        "strategy_name": "reversal",
        "initial_capital": 100_000.0,
        "cost_bps": 0.0,
        "rebalance": RebalanceFreq.DAILY,
    }
    fields.update(overrides)
    return BacktestConfig(**fields)


ASSET_A = "A"
ASSET_B = "B"
ASSET_C = "C"

# 同 Momentum 测试的确定性趋势:A 涨、B 平、C 跌。
TREND: dict[str, list[float]] = {
    "2024-01-02": [10.0, 10.0, 10.0],
    "2024-01-03": [11.0, 10.0, 9.0],
    "2024-01-04": [12.0, 10.0, 8.0],
    "2024-01-05": [13.0, 10.0, 7.0],
}


def _trend_frame() -> pd.DataFrame:
    return _prices(TREND, [ASSET_A, ASSET_B, ASSET_C])


# ---------------------------------------------------------------------------
# 1) bottom-k selects lowest momentum
# ---------------------------------------------------------------------------


def test_bottom_k_selects_lowest_momentum() -> None:
    # lookback=2, bottom_k=1:t2 起 C 动量最低 → 全仓 C。
    target = ReversalStrategy(lookback=2, bottom_k=1).weights(_trend_frame())
    for ts in [_ts("2024-01-02"), _ts("2024-01-03")]:
        assert target.loc[ts].sum() == pytest.approx(0.0)
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        assert target.loc[ts, ASSET_C] == pytest.approx(1.0)
        assert target.loc[ts, ASSET_A] == pytest.approx(0.0)
        assert target.loc[ts, ASSET_B] == pytest.approx(0.0)


def test_bottom_k_equal_weight() -> None:
    # bottom_k=2:t2 起 B(0.0)、C(-0.2) 为最低 2 → 等权 0.5;A 不选。
    target = ReversalStrategy(lookback=2, bottom_k=2).weights(_trend_frame())
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        assert target.loc[ts, ASSET_B] == pytest.approx(0.5)
        assert target.loc[ts, ASSET_C] == pytest.approx(0.5)
        assert target.loc[ts, ASSET_A] == pytest.approx(0.0)
    assert np.allclose(target.iloc[2:].sum(axis=1).to_numpy(), 1.0)


def test_insufficient_lookback_is_cash() -> None:
    target = ReversalStrategy(lookback=2, bottom_k=1).weights(_trend_frame())
    assert target.iloc[0].sum() == pytest.approx(0.0)
    assert target.iloc[1].sum() == pytest.approx(0.0)


def test_universe_smaller_than_k_takes_all_equal_weight() -> None:
    target = ReversalStrategy(lookback=2, bottom_k=5).weights(_trend_frame())
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        for asset in (ASSET_A, ASSET_B, ASSET_C):
            assert target.loc[ts, asset] == pytest.approx(1.0 / 3)
    assert np.allclose(target.iloc[2:].sum(axis=1).to_numpy(), 1.0)


# ---------------------------------------------------------------------------
# 2) parameter validation
# ---------------------------------------------------------------------------


def test_lookback_must_be_positive() -> None:
    with pytest.raises(ValueError, match="lookback"):
        ReversalStrategy(lookback=0, bottom_k=1)


def test_bottom_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="bottom_k"):
        ReversalStrategy(lookback=2, bottom_k=0)


# ---------------------------------------------------------------------------
# 3) anti-look-ahead + anti-double-lag
# ---------------------------------------------------------------------------


def test_future_price_does_not_move_past_signals() -> None:
    base = _trend_frame()
    var = _prices(
        {
            "2024-01-02": [10.0, 10.0, 10.0],
            "2024-01-03": [11.0, 10.0, 9.0],
            "2024-01-04": [12.0, 10.0, 8.0],
            "2024-01-05": [13.0, 10.0, 1.0],  # C 暴跌:动量变更低
        },
        [ASSET_A, ASSET_B, ASSET_C],
    )
    w_base = ReversalStrategy(lookback=2, bottom_k=1).weights(base)
    w_var = ReversalStrategy(lookback=2, bottom_k=1).weights(var)
    pd.testing.assert_frame_equal(w_base.iloc[:3], w_var.iloc[:3])
    # 两版 01-05 都选 C(C 在 base 已是最低,var 更低),但确认历史信号不受影响。
    assert w_base.loc[_ts("2024-01-05"), ASSET_C] == pytest.approx(1.0)
    assert w_var.loc[_ts("2024-01-05"), ASSET_C] == pytest.approx(1.0)


def test_signal_at_t_moves_holding_at_t_plus_one() -> None:
    res = run_backtest(
        _trend_frame(),
        ReversalStrategy(lookback=2, bottom_k=1),
        _config(universe=(ASSET_A, ASSET_B, ASSET_C)),
    )
    holdings = res.positions
    t2 = _ts("2024-01-04")
    t3 = _ts("2024-01-05")
    assert holdings.loc[t2, ASSET_C] == pytest.approx(0.0)
    assert holdings.loc[t3, ASSET_C] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 4) symmetry with Momentum — selections are complementary
# ---------------------------------------------------------------------------


def test_reversal_is_mirror_of_momentum() -> None:
    # 同 lookback、k=1:Momentum 选最高(A)、Reversal 选最低(C),选股不重叠。
    prices = _trend_frame()
    m = MomentumStrategy(lookback=2, top_k=1).weights(prices)
    r = ReversalStrategy(lookback=2, bottom_k=1).weights(prices)
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        assert m.loc[ts, ASSET_A] == pytest.approx(1.0)
        assert r.loc[ts, ASSET_C] == pytest.approx(1.0)
        # 两者持仓逐资产乘积为 0(选股集合不相交)。
        assert (m.loc[ts] * r.loc[ts]).sum() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 5) protocol + shape + end-to-end
# ---------------------------------------------------------------------------


def test_satisfies_strategy_protocol_and_shape() -> None:
    strat = ReversalStrategy(lookback=2, bottom_k=1)
    assert isinstance(strat, Strategy)
    prices = _trend_frame()
    target = strat.weights(prices)
    assert target.shape == prices.shape
    assert not target.iloc[0].isna().any()
    row_sums = target.sum(axis=1)
    assert (row_sums >= -1e-9).all()
    assert (row_sums <= 1.0 + 1e-9).all()


def test_end_to_end_engine_produces_result() -> None:
    # 选 C(跌)→ 持有段 equity 下跌(动量反转做多最弱资产,亏损)。
    res = run_backtest(
        _trend_frame(),
        ReversalStrategy(lookback=2, bottom_k=1),
        _config(universe=(ASSET_A, ASSET_B, ASSET_C)),
    )
    assert res.equity_curve.iloc[-1] < res.equity_curve.iloc[0]
    assert res.equity_curve.iloc[0] == 100_000.0
    assert res.daily_returns.iloc[0] == 0.0
    assert res.metrics is None
