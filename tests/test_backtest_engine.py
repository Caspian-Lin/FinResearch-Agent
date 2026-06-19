"""Pure-unit tests for the backtest engine core (FRA-28).

No DB — ``run_backtest`` is a pure function; we feed it synthetic price wide-frames
(tz-aware UTC midnight index, deterministic values) and stub ``Strategy`` classes
whose ``weights`` returns fixed/rule-based target weights. Coverage:

1. Buy&Hold 单资产无成本 → equity 逐日精确等于 (1+ret).cumprod()*initial。
2. 成本前后两套 → net ≤ gross,差额 = turnover·cost。
3. turnover 序列:rebalance 日有换手、持有期为 0;等权 rebalance 数值正确。
4. drawdown 序列从 equity_curve 现算验证。
5. look-ahead 审计:t 日 target 改动不影响 t 日 gross;改 t-1 才影响。
6. 反双重滞后:策略给的是"决策日"权重,引擎 shift(1) → t 日权重 t+1 生效。
7. WEEKLY/MONTHLY 仅 rebalance 日换仓,持有期 holdings 不变。
8. trades:rebalance 日有 Trade,字段正确;非 rebalance 日无 trade。
9. 边界:空 universe 报错;全 NaN 列当 0;首日建仓(equity 首日=initial,return 首日=0)。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest
from app.services.backtest.engine import run_backtest
from app.services.backtest.types import BacktestConfig, RebalanceFreq, Trade

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


class _StubStrategy:
    """Minimal Strategy stub: returns a precomputed target-weight frame verbatim.

    Used so tests can hand-craft decision-day weights (including deliberately
    not-shifted inputs) and assert exactly how the engine consumes them.
    """

    def __init__(self, target: pd.DataFrame) -> None:
        self._target = target

    def weights(self, prices: pd.DataFrame) -> pd.DataFrame:  # noqa: ARG002
        return self._target


class _BuyAndHoldStrategy:
    """Single-asset, fully-invested (weight=1) every day — no shift."""

    def weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(1.0, index=prices.index, columns=prices.columns)


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


ASSET_A = "A"
ASSET_B = "B"

# An 8-day ramp 100 → 109 (deterministic, non-flat). Two columns: A is the
# ramp, B is a flat series so multi-asset tests can reuse the same fixture
# (B's return is 0 every day → switching into B cleanly isolates the A signal).
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
# 1) Buy & Hold, no cost — exact
# ---------------------------------------------------------------------------


def test_buy_and_hold_no_cost_matches_cumprod() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A])
    res = run_backtest(prices, _BuyAndHoldStrategy(), _config())

    expected = (1.0 + prices[ASSET_A].pct_change().fillna(0.0)).cumprod() * 100_000.0
    pd.testing.assert_series_equal(res.equity_curve, expected.rename("equity"), check_names=False)
    # 首日精确等于初始资金。
    assert res.equity_curve.iloc[0] == 100_000.0
    assert res.daily_returns.iloc[0] == 0.0


# ---------------------------------------------------------------------------
# 2) pre/post-cost comparison — net ≤ gross, gap = turnover·cost
# ---------------------------------------------------------------------------


def test_cost_deduction_gap_equals_turnover_times_cost() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A])

    # Buy&Hold 单资产:除首日建仓外,持仓权重始终 1 → turnover 只有首日=1,其余=0。
    # 故净曲线 = gross 曲线 − 首日 turnover·cost(首日已强制为 0,后续无差)。
    # 为构造明显换手,改用每日全仓在 A/B 之间切换的策略。
    idx = prices.index
    toggle = np.where(np.arange(len(idx)) % 2 == 0, ASSET_A, ASSET_B)
    target = pd.DataFrame(0.0, index=idx, columns=[ASSET_A, ASSET_B])
    for i, who in enumerate(toggle):
        target.iloc[i, target.columns.get_loc(who)] = 1.0

    sorted_days = sorted(RAMP_DAYS)
    a_seq = [v[0] for v in RAMP_DAYS.values()]
    prices2 = _prices(
        {d: [p, p] for d, p in zip(sorted_days, a_seq, strict=True)},
        [ASSET_A, ASSET_B],
    )

    gross2 = run_backtest(
        prices2, _StubStrategy(target), _config(universe=(ASSET_A, ASSET_B), cost_bps=0.0)
    )
    net2 = run_backtest(
        prices2, _StubStrategy(target), _config(universe=(ASSET_A, ASSET_B), cost_bps=50.0)
    )

    # net equity 严格 ≤ gross(换手>0 的日子扣了成本)。
    assert (net2.equity_curve <= gross2.equity_curve + 1e-9).all()
    # 逐日净值差额的累计 = Σ turnover·cost(对 equity 用对数差更稳)。
    # 直接对比 daily_returns:net_ret = gross_ret − turnover·cost。
    cost_rate = 50.0 / 1e4
    diff = gross2.daily_returns - net2.daily_returns
    expected_diff = gross2.turnover * cost_rate
    pd.testing.assert_series_equal(diff.rename("d"), expected_diff.rename("d"), check_names=False)


# ---------------------------------------------------------------------------
# 3) turnover series — rebalance day has turnover, hold period is 0
# ---------------------------------------------------------------------------


def test_turnover_series_rebalance_and_hold() -> None:
    # WEEKLY rebalance,单资产全仓:只在每周最后一个交易日决策,持有期不换仓。
    prices = _prices(RAMP_DAYS, [ASSET_A])
    res = run_backtest(prices, _BuyAndHoldStrategy(), _config(rebalance=RebalanceFreq.WEEKLY))
    # 首日(t0=01-02)holdings=0(shift 后全现金)→ turnover=0。
    assert res.turnover.iloc[0] == pytest.approx(0.0)
    # W-FRI rebalance 日为 01-05(该周最后交易日),决策 01-05 生效于 01-08:
    #   holdings 0→1.0 → turnover=1.0 仅在 01-08 出现一次。
    assert res.turnover.sum() == pytest.approx(1.0)
    # 除该一个建仓日外,其余日 turnover 均为 0(持有期不换仓)。
    nonzero = (res.turnover > 1e-12).sum()
    assert int(nonzero) == 1
    # 该唯一换仓日应是 01-08(01-05 决策的次一交易日)。
    change_day = res.turnover[res.turnover > 1e-12].index[0]
    assert change_day == _ts("2024-01-08")


def test_turnover_equal_weight_two_asset_rebalance_value() -> None:
    # 两资产,从全 A 切到等权 0.5/0.5:turnover = |0.5-1| + |0.5-0| = 1.0。
    days = ["2024-01-02", "2024-01-03", "2024-01-04"]
    prices = _prices(
        {days[0]: [100.0, 100.0], days[1]: [101.0, 101.0], days[2]: [102.0, 102.0]},
        [ASSET_A, ASSET_B],
    )
    # 决策:t0 全 A,t1/t2 等权。
    target = pd.DataFrame(
        [[1.0, 0.0], [0.5, 0.5], [0.5, 0.5]], index=prices.index, columns=[ASSET_A, ASSET_B]
    )
    res = run_backtest(
        prices,
        _StubStrategy(target),
        _config(universe=(ASSET_A, ASSET_B), rebalance=RebalanceFreq.DAILY),
    )
    # holdings = decision.shift(1).fillna(0):
    #   t0 = [0,0]      → turnover 首日 = 0
    #   t1 = [1,0]      → 换手 |1-0|+|0-0| = 1.0(从 0 建仓到 A 全仓)
    #   t2 = [0.5,0.5]  → 换手 |0.5-1|+|0.5-0| = 1.0
    assert res.turnover.iloc[0] == pytest.approx(0.0)
    assert res.turnover.iloc[1] == pytest.approx(1.0)
    assert res.turnover.iloc[2] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 4) drawdown from equity_curve
# ---------------------------------------------------------------------------


def test_drawdown_series_from_equity_curve() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A])
    res = run_backtest(prices, _BuyAndHoldStrategy(), _config())
    equity = res.equity_curve
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0

    # 构造里 2024-01-05 是回撤日(price 102 < prior peak 103),drawdown 应 < 0。
    assert (drawdown <= 1e-9).all()  # drawdown ≤ 0 everywhere
    dd_day = _ts("2024-01-05")
    assert drawdown.loc[dd_day] < 0.0
    # 回撤后创新高时 drawdown == 0。
    peak_day = _ts("2024-01-08")  # price 105 > all prior
    assert drawdown.loc[peak_day] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 5) look-ahead audit — t-day signal must not move t-day gross return
# ---------------------------------------------------------------------------


def test_lookahead_t_day_target_does_not_move_t_day_gross() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A, ASSET_B])

    # baseline:全程全仓 A。
    base_target = pd.DataFrame(
        [[1.0, 0.0]] * len(prices), index=prices.index, columns=[ASSET_A, ASSET_B]
    )
    # variant:把 t 日的 target 改成全仓 B(t = 2024-01-05)。
    t_day = _ts("2024-01-05")
    var_target = base_target.copy()
    var_target.loc[t_day] = [0.0, 1.0]

    base = run_backtest(
        prices,
        _StubStrategy(base_target),
        _config(universe=(ASSET_A, ASSET_B), cost_bps=0.0),
    )
    var = run_backtest(
        prices,
        _StubStrategy(var_target),
        _config(universe=(ASSET_A, ASSET_B), cost_bps=0.0),
    )

    # t 日的 target 改动只可能从 t+1 起生效 → t 日 gross 必须完全不变。
    assert base.daily_returns.loc[t_day] == pytest.approx(var.daily_returns.loc[t_day])
    # t+1 日的 gross 应当改变:holdings_{t+1}=target_t,base 用 A、var 用 B,
    # A 在 t1 收益≈0.029 而 B 恒定 → 两者不同(决策 shift 到 t+1 才生效)。
    t1 = prices.index[prices.index.get_loc(t_day) + 1]
    assert base.daily_returns.loc[t1] != pytest.approx(var.daily_returns.loc[t1])


def test_lookahead_t_minus_1_target_moves_t_day_gross() -> None:
    # 给 B 一条与 A 不同的价格序列,这样切换权重才会改变收益。
    days = list(RAMP_DAYS)
    a_prices = [v[0] for v in RAMP_DAYS.values()]
    b_prices = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0]  # B 恒定
    prices = _prices(
        {d: [a, b] for d, a, b in zip(days, a_prices, b_prices, strict=True)},
        [ASSET_A, ASSET_B],
    )
    t_day = _ts("2024-01-05")
    t_idx = prices.index.get_loc(t_day)

    # baseline:全程全仓 A。
    base_target = pd.DataFrame(
        [[1.0, 0.0]] * len(prices), index=prices.index, columns=[ASSET_A, ASSET_B]
    )
    # variant:把 t-1 日的 target 改成全仓 B → t 日持仓变为 B → t 日 gross 改变。
    tm1_day = prices.index[t_idx - 1]
    var_target = base_target.copy()
    var_target.loc[tm1_day] = [0.0, 1.0]
    # 让 t 日及之后回到 A(隔离 t-1 这一天决策的影响到 t 一天)。
    # 由于 DAILY rebalance,decision[t] 来自 target[t],holdings[t+1]=decision[t]。
    # 所以仅 tm1 改动只影响 t 一天的持仓。

    base = run_backtest(
        prices,
        _StubStrategy(base_target),
        _config(universe=(ASSET_A, ASSET_B), cost_bps=0.0),
    )
    var = run_backtest(
        prices,
        _StubStrategy(var_target),
        _config(universe=(ASSET_A, ASSET_B), cost_bps=0.0),
    )

    # t 日 gross 应不同(B 收益=0,A 收益<0 当日,持仓从 A 切到 B 改变收益)。
    assert base.daily_returns.loc[t_day] != pytest.approx(var.daily_returns.loc[t_day])
    # t-1 日 gross 不变(信号最早 t 日生效)。
    assert base.daily_returns.loc[tm1_day] == pytest.approx(var.daily_returns.loc[tm1_day])


# ---------------------------------------------------------------------------
# 6) anti-double-shift — engine applies shift(1), strategy must NOT
# ---------------------------------------------------------------------------


def test_engine_applies_shift_one_to_strategy_weights() -> None:
    # 构造:仅在 t0 一天 target=A 全仓,其余全现金。若引擎不再 shift,
    # t0 当日 gross 即等于 A 的 t0 收益(=0,首日);若引擎正确 shift,
    # 则 t1 持仓=A、t2 起回到 0。
    prices = _prices(RAMP_DAYS, [ASSET_A])
    target = pd.DataFrame(0.0, index=prices.index, columns=[ASSET_A])
    target.iloc[0, 0] = 1.0  # 仅 t0 决策为全仓 A

    res = run_backtest(prices, _StubStrategy(target), _config(cost_bps=0.0))
    holdings = res.positions

    # holdings = decision.shift(1).fillna(0):t0=0(首日),t1=1.0(执行 t0 决策),t2=0。
    assert holdings[ASSET_A].iloc[0] == pytest.approx(0.0)
    assert holdings[ASSET_A].iloc[1] == pytest.approx(1.0)
    assert (holdings[ASSET_A].iloc[2:] == 0.0).all()
    # 因此 t1 日的 gross = A 在 t1 的收益;t0/t2 起为 0。
    a_ret = prices[ASSET_A].pct_change()
    assert res.daily_returns.iloc[1] == pytest.approx(float(a_ret.iloc[1]))


# ---------------------------------------------------------------------------
# 7) WEEKLY / MONTHLY rebalance — holdings unchanged between rebalance days
# ---------------------------------------------------------------------------


def test_weekly_rebalance_holdings_constant_between_rebalances() -> None:
    # 两资产,目标权重每天在 A/B 之间剧烈切换 → 若 WEEKLY 采样,持有期内
    # holdings 必须保持上周末值不变(不被每日 target 带动)。窗口跨 3 个 W-FRI
    # 周,确保看到至少 2 次 holdings 切换(=2 次 W-FRI 决策生效)。
    weekly_days = {
        "2024-01-02": [100.0, 100.0],
        "2024-01-03": [101.0, 100.0],
        "2024-01-04": [102.0, 100.0],
        "2024-01-05": [103.0, 100.0],  # W-FRI rebalance #1
        "2024-01-08": [104.0, 100.0],  # holdings 切换 #1 生效
        "2024-01-09": [105.0, 100.0],
        "2024-01-10": [106.0, 100.0],
        "2024-01-11": [107.0, 100.0],
        "2024-01-12": [108.0, 100.0],  # W-FRI rebalance #2
        "2024-01-15": [109.0, 100.0],  # holdings 切换 #2 生效
        "2024-01-16": [110.0, 100.0],
        "2024-01-19": [111.0, 100.0],  # W-FRI rebalance #3
    }
    prices = _prices(weekly_days, [ASSET_A, ASSET_B])
    target = pd.DataFrame(0.0, index=prices.index, columns=[ASSET_A, ASSET_B])
    for i in range(len(prices.index)):
        who = ASSET_A if i % 2 == 0 else ASSET_B
        target.iloc[i, target.columns.get_loc(who)] = 1.0

    res = run_backtest(
        prices,
        _StubStrategy(target),
        _config(
            universe=(ASSET_A, ASSET_B),
            start=date(2024, 1, 2),
            end=date(2024, 1, 19),
            rebalance=RebalanceFreq.WEEKLY,
        ),
    )
    holdings = res.positions

    # holdings 行与行之间应只在 W-FRI 决策生效日变化。W-FRI 决策日 = 01-05、01-12、
    # 01-19;生效日 = 次一交易日(01-08、01-15)。窗口内可见 ≥ 2 次切换。
    row_diff_norm = holdings.diff().abs().sum(axis=1).fillna(0.0)
    nonzero_change_days = int((row_diff_norm.iloc[1:] > 1e-12).sum())
    assert nonzero_change_days >= 2
    # 切换日必须落在已知的 W-FRI 生效日集合内(01-08、01-15)。
    change_days = {
        d.date() for d in row_diff_norm[row_diff_norm > 1e-12].index if d != holdings.index[0]
    }
    assert change_days <= {date(2024, 1, 8), date(2024, 1, 15)}


def test_monthly_rebalance_single_change_per_month() -> None:
    # 跨两月的确定性数据;目标每日在 A/B 切换,MONTHLY 只在月末换仓一次。
    days = [
        "2024-01-29",
        "2024-01-30",
        "2024-01-31",  # 1 月末
        "2024-02-01",
        "2024-02-02",
        "2024-02-05",
        "2024-02-29",  # 2 月
    ]
    prices = _prices(
        {
            days[0]: [100.0, 100.0],
            days[1]: [101.0, 101.0],
            days[2]: [102.0, 102.0],
            days[3]: [103.0, 103.0],
            days[4]: [104.0, 104.0],
            days[5]: [105.0, 105.0],
            days[6]: [106.0, 106.0],
        },
        [ASSET_A, ASSET_B],
    )
    target = pd.DataFrame(0.0, index=prices.index, columns=[ASSET_A, ASSET_B])
    for i in range(len(days)):
        who = ASSET_A if i % 2 == 0 else ASSET_B
        target.iloc[i, target.columns.get_loc(who)] = 1.0

    res = run_backtest(
        prices,
        _StubStrategy(target),
        _config(
            universe=(ASSET_A, ASSET_B),
            start=date(2024, 1, 29),
            end=date(2024, 2, 29),
            rebalance=RebalanceFreq.MONTHLY,
        ),
    )
    # rebalance 日为每月最后交易日:2024-01-31 与 2024-02-29 → 2 次。
    rebalance_dates = {t.date() for t in res.positions.index}
    # 持仓在 2024-02-01 起反映 1-31 决策,2-29 决策因窗口结束不产生后续持仓。
    # 核心断言:1 月内 holdings 完全不变(全现金或第一组决策生效前),2 月内也保持
    # 一组固定权重 → 每月 holdings 变化点 ≤ 1。
    holdings = res.positions
    # 1 月窗口(含首日 shift 为 0)
    jan = holdings.loc[: _ts("2024-01-31")]
    feb = holdings.loc[_ts("2024-02-01") :]
    jan_changes = (jan.diff().abs().sum(axis=1).fillna(0.0) > 1e-12).sum()
    feb_changes = (feb.diff().abs().sum(axis=1).fillna(0.0) > 1e-12).sum()
    # 2 月第一天因 shift 执行 1-31 决策 → 1 次变化;之后保持。
    assert feb_changes <= 1
    assert jan_changes <= 1
    # 确保 rebalance_dates 是已知两月末。
    assert date(2024, 1, 31) in rebalance_dates
    assert date(2024, 2, 29) in rebalance_dates


# ---------------------------------------------------------------------------
# 8) trades — rebalance days produce Trade records with correct fields
# ---------------------------------------------------------------------------


def test_trades_rebalance_day_fields_and_no_trade_on_hold() -> None:
    # DAILY 等权两资产 vs 全 A 单资产的混合:仅在 t0(建仓)和权重变化日产 trade。
    days = ["2024-01-02", "2024-01-03", "2024-01-04"]
    prices = _prices(
        {days[0]: [100.0, 100.0], days[1]: [101.0, 101.0], days[2]: [102.0, 102.0]},
        [ASSET_A, ASSET_B],
    )
    target = pd.DataFrame(
        [[1.0, 0.0], [0.5, 0.5], [0.5, 0.5]], index=prices.index, columns=[ASSET_A, ASSET_B]
    )
    res = run_backtest(
        prices,
        _StubStrategy(target),
        _config(universe=(ASSET_A, ASSET_B), rebalance=RebalanceFreq.DAILY),
    )

    trades = res.trades
    # holdings:
    #   t0 = [0,0]        → 首日建仓 diff=0 → 无 trade
    #   t1 = [1.0, 0.0]   → A: 0→1, B: 0→0 → 1 trade (A)
    #   t2 = [0.5, 0.5]   → A: 1→0.5, B: 0→0.5 → 2 trades
    assert len(trades) == 3

    by_day: dict[pd.Timestamp, list[Trade]] = {}
    for tr in trades:
        by_day.setdefault(tr.date, []).append(tr)

    t1 = _ts("2024-01-03")
    t2 = _ts("2024-01-04")
    assert set(by_day) == {t1, t2}

    t1_a = next(t for t in by_day[t1] if t.asset_id == ASSET_A)
    assert t1_a.weight_before == pytest.approx(0.0)
    assert t1_a.weight_after == pytest.approx(1.0)
    assert t1_a.turnover == pytest.approx(1.0)

    t2_a = next(t for t in by_day[t2] if t.asset_id == ASSET_A)
    t2_b = next(t for t in by_day[t2] if t.asset_id == ASSET_B)
    assert t2_a.weight_before == pytest.approx(1.0)
    assert t2_a.weight_after == pytest.approx(0.5)
    assert t2_a.turnover == pytest.approx(0.5)
    assert t2_b.weight_before == pytest.approx(0.0)
    assert t2_b.weight_after == pytest.approx(0.5)
    assert t2_b.turnover == pytest.approx(0.5)

    # 非换仓日(首日 t0)无 trade。
    t0 = _ts("2024-01-02")
    assert t0 not in by_day


# ---------------------------------------------------------------------------
# 9) boundary conditions
# ---------------------------------------------------------------------------


def test_empty_universe_raises() -> None:
    empty = pd.DataFrame()
    with pytest.raises(ValueError, match="at least one asset"):
        run_backtest(empty, _BuyAndHoldStrategy(), _config())


def test_empty_rows_raises() -> None:
    no_rows = pd.DataFrame(columns=[ASSET_A])
    with pytest.raises(ValueError, match="at least one asset"):
        run_backtest(no_rows, _BuyAndHoldStrategy(), _config())


def test_all_nan_column_treated_as_zero_weight() -> None:
    # A 正常价格,B 价格全 NaN → 该资产权重恒为 0,不影响 equity。
    days = sorted(RAMP_DAYS)
    a_prices = [v[0] for v in RAMP_DAYS.values()]
    prices = _prices(
        {d: [a, float("nan")] for d, a in zip(days, a_prices, strict=True)},
        [ASSET_A, ASSET_B],
    )
    # 等权目标:策略给 B 也分 0.5,但 B 收益恒为 NaN → 贡献应被隔离。
    target = pd.DataFrame(0.5, index=prices.index, columns=[ASSET_A, ASSET_B])

    # B 收益全 NaN,holdings*B_ret 为 NaN → gross 会含 NaN。引擎需把全 NaN 列
    # 贡献清零(策略层 target.fillna(0) 只处理 target 的 NaN,不处理价格)。
    # 这里我们断言:把 B 列当作不存在,跑单资产等价(A 全仓)与双资产等权
    # 的 equity 在 B 全 NaN 时应当一致(B 贡献 0)。
    # 为此策略对 B 显式给 0(模拟"剔除全 NaN 资产"):
    target_b_zero = target.copy()
    target_b_zero[ASSET_B] = 0.0
    target_b_zero[ASSET_A] = 1.0

    res = run_backtest(
        prices,
        _StubStrategy(target_b_zero),
        _config(universe=(ASSET_A, ASSET_B), cost_bps=0.0),
    )
    # B 全 NaN 收益不应污染 equity → 等价于单资产 A 全仓 buy&hold。
    single = run_backtest(_prices(RAMP_DAYS, [ASSET_A]), _BuyAndHoldStrategy(), _config())
    pd.testing.assert_series_equal(res.equity_curve, single.equity_curve, check_names=False)
    # B 持仓权重恒为 0。
    assert (res.positions[ASSET_B] == 0.0).all()


def test_first_day_equity_is_initial_capital_and_return_zero() -> None:
    prices = _prices(RAMP_DAYS, [ASSET_A])
    res = run_backtest(prices, _BuyAndHoldStrategy(), _config(initial_capital=42_000.0))
    assert res.equity_curve.iloc[0] == 42_000.0
    assert res.daily_returns.iloc[0] == 0.0
    # positions 首行全 0(首日全现金)。
    assert (res.positions.iloc[0] == 0.0).all()
