"""Risk-metric unit tests (FRA-34) — 纯单元,无 DB,手算 / pandas 独立对照。

覆盖 §11.2 全部 9 个指标的年化约定、gross/net 双口径、退化与边界输入,以及
``to_metrics_orm`` 的 18 列映射(inf → None)。
"""

from __future__ import annotations

import math
import uuid
from datetime import date

import numpy as np
import pandas as pd
import pytest
from app.services.backtest.metrics import (
    compute_result_metrics,
    compute_risk_metrics,
    to_metrics_orm,
)
from app.services.backtest.types import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    RebalanceFreq,
)


def _series(values: list[float], name: str = "r") -> pd.Series:
    return pd.Series(values, name=name).astype("float64")


def _zero(name: str = "t", n: int = 4) -> pd.Series:
    return pd.Series([0.0] * n, name=name).astype("float64")


def _config(**overrides: object) -> BacktestConfig:
    base: dict[str, object] = {
        "universe": ("A",),
        "start": date(2024, 1, 2),
        "end": date(2024, 1, 10),
        "strategy_name": "stub",
        "initial_capital": 100_000.0,
        "cost_bps": 0.0,
        "rebalance": RebalanceFreq.DAILY,
    }
    base.update(overrides)
    return BacktestConfig(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# compute_risk_metrics — 9 指标手算 / pandas 对照
# ---------------------------------------------------------------------------


def test_annual_return_volatility_sharpe_arithmetic_annualization() -> None:
    """年化:收益 ×252、波动 ×√252、Sharpe = (mean/std)×√252 (rf=0)。"""
    rets = _series([0.0, 0.01, -0.02, 0.03, 0.01])
    m = compute_risk_metrics(rets, _zero(n=5))
    mean = rets.mean()
    std = rets.std(ddof=1)
    assert m.annual_return == pytest.approx(mean * 252)
    assert m.volatility == pytest.approx(std * np.sqrt(252))
    assert m.sharpe_ratio == pytest.approx((mean / std) * np.sqrt(252))


def test_sharpe_with_risk_free_rate() -> None:
    """rf 年化:sharpe = (mean − rf/252)/std × √252 == (annual_return − rf)/vol。"""
    rets = _series([0.01, 0.02, -0.005, 0.015, 0.005, 0.012])
    m = compute_risk_metrics(rets, _zero(n=6), risk_free_rate=0.02)
    mean = rets.mean()
    std = rets.std(ddof=1)
    expected = ((mean - 0.02 / 252) / std) * np.sqrt(252)
    assert m.sharpe_ratio == pytest.approx(expected)


def test_max_drawdown_and_calmar() -> None:
    """maxDD = equity/cummax − 1 最小值;calmar = annual_return/|maxDD|。"""
    # 100 → 120 → 90 → 95:峰值 120、谷底 90 → 回撤 90/120 − 1 = −0.25。
    prices = pd.Series([100.0, 120.0, 90.0, 95.0]).pct_change().fillna(0.0)
    m = compute_risk_metrics(prices, _zero(n=4))
    assert m.max_drawdown == pytest.approx(-0.25)
    assert m.calmar_ratio == pytest.approx(m.annual_return / 0.25)


def test_max_drawdown_zero_when_monotonic_up_gives_inf_calmar() -> None:
    """单调上涨无回撤 → maxDD = 0、calmar = inf(ORM 映射时转 None)。"""
    prices = pd.Series([100.0, 101.0, 102.0, 103.0]).pct_change().fillna(0.0)
    m = compute_risk_metrics(prices, _zero(n=4))
    assert m.max_drawdown == pytest.approx(0.0, abs=1e-12)
    assert math.isinf(m.calmar_ratio)


def test_turnover_annualized_mean_times_252() -> None:
    rets = _series([0.0, 0.01, 0.02, 0.0])
    turnover = _series([0.0, 0.4, 0.2, 0.4], name="t")
    m = compute_risk_metrics(rets, turnover)
    assert m.turnover == pytest.approx(turnover.mean() * 252)


def test_win_rate_positive_days_share() -> None:
    """win_rate = P(ret > 0),含 0 收益日计入分母。"""
    rets = _series([0.0, 0.01, -0.02, 0.03, 0.0, 0.02])  # 3 个正收益 / 6
    m = compute_risk_metrics(rets, _zero(n=6))
    assert m.win_rate == pytest.approx((rets > 0).mean())
    assert m.win_rate == pytest.approx(3 / 6)


def test_beta_correlation_against_benchmark() -> None:
    """Beta = cov(r,b)/var(b);Correlation = Pearson r(共同窗口)。"""
    r = _series([0.01, -0.02, 0.03, 0.005, -0.01, 0.02])
    b = _series([0.02, -0.01, 0.015, 0.0, -0.005, 0.025], name="b")
    m = compute_risk_metrics(r, _zero(n=6), benchmark_returns=b)
    df = pd.concat([r.rename("r"), b.rename("b")], axis=1)
    assert m.beta == pytest.approx(df["r"].cov(df["b"]) / df["b"].var(ddof=1))
    assert m.correlation == pytest.approx(df["r"].corr(df["b"]))


def test_beta_correlation_zero_without_benchmark() -> None:
    r = _series([0.01, -0.02, 0.03])
    m = compute_risk_metrics(r, _zero(n=3))
    assert m.beta == 0.0
    assert m.correlation == 0.0


def test_beta_zero_when_benchmark_constant() -> None:
    """benchmark 方差 0 → beta/corr = 0(避免除零)。"""
    r = _series([0.01, 0.02, -0.01, 0.03])
    b = _series([0.005, 0.005, 0.005, 0.005], name="b")
    m = compute_risk_metrics(r, _zero(n=4), benchmark_returns=b)
    assert m.beta == 0.0
    assert m.correlation == 0.0


def test_degenerate_empty_returns_all_zero() -> None:
    m = compute_risk_metrics(pd.Series([], dtype="float64"), pd.Series([], dtype="float64"))
    assert m == BacktestMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# compute_result_metrics — gross vs net 双口径
# ---------------------------------------------------------------------------


def _result(gross: pd.Series, net: pd.Series, turnover: pd.Series) -> BacktestResult:
    idx = pd.date_range("2024-01-02", periods=len(net), freq="D", tz="UTC")
    gross = gross.set_axis(idx)
    net = net.set_axis(idx)
    turnover = turnover.set_axis(idx)
    return BacktestResult(
        config=_config(),
        equity_curve=(1.0 + net).cumprod() * 100_000.0,
        daily_returns=net,
        turnover=turnover,
        positions=pd.DataFrame(0.0, index=idx, columns=["A"]),
        gross_returns=gross,
    )


def test_result_metrics_gross_and_net_pair() -> None:
    """gross 用 gross_returns、net 用 daily_returns;turnover 共用,成本压低净收益。"""
    gross = _series([0.0, 0.01, -0.02, 0.03, 0.01])
    net = _series([0.0, 0.008, -0.022, 0.028, 0.008])
    turnover = _series([0.0, 0.1, 0.0, 0.2, 0.0], name="t")
    g, n = compute_result_metrics(_result(gross, net, turnover))
    assert g.annual_return == pytest.approx(gross.mean() * 252)
    assert n.annual_return == pytest.approx(net.mean() * 252)
    assert g.annual_return > n.annual_return
    assert g.turnover == n.turnover


def test_result_metrics_gross_equals_net_when_no_cost() -> None:
    """cost_bps=0 → gross 序列 == net 序列,两组指标完全相等(浮点)。"""
    rets = _series([0.0, 0.01, -0.02, 0.03, 0.01])
    turnover = _series([0.0, 0.1, 0.0, 0.2, 0.0], name="t")
    g, n = compute_result_metrics(_result(rets, rets, turnover))
    assert g == n


def test_result_metrics_passes_benchmark_and_rf() -> None:
    """compute_result_metrics 透传 benchmark_returns / risk_free_rate。"""
    idx = pd.date_range("2024-01-02", periods=5, freq="D", tz="UTC")
    gross = _series([0.0, 0.01, 0.02, -0.005, 0.015]).set_axis(idx)
    turnover = _series([0.0, 0.1, 0.0, 0.2, 0.0], name="t").set_axis(idx)
    bench = _series([0.0, 0.012, 0.008, -0.002, 0.01], name="b").set_axis(idx)
    result = _result(gross, gross, turnover)
    g, _ = compute_result_metrics(result, benchmark_returns=bench, risk_free_rate=0.01)
    df = pd.concat([gross.rename("r"), bench.rename("b")], axis=1)
    assert g.beta == pytest.approx(df["r"].cov(df["b"]) / df["b"].var(ddof=1))
    assert g.correlation == pytest.approx(df["r"].corr(df["b"]))


# ---------------------------------------------------------------------------
# to_metrics_orm — 18 列映射
# ---------------------------------------------------------------------------


def test_to_metrics_orm_field_mapping() -> None:
    gross = compute_risk_metrics(
        _series([0.0, 0.01, -0.02, 0.03]), _series([0.0, 0.1, 0.0, 0.2], name="t")
    )
    net = compute_risk_metrics(
        _series([0.0, 0.008, -0.022, 0.028]), _series([0.0, 0.1, 0.0, 0.2], name="t")
    )
    run_id = uuid.uuid4()
    orm = to_metrics_orm(run_id, gross, net)
    assert orm.backtest_run_id == run_id
    assert orm.gross_annual_return == Decimal_str(gross.annual_return)
    assert orm.net_annual_return == Decimal_str(net.annual_return)
    assert orm.gross_beta == Decimal_str(gross.beta)
    assert orm.net_win_rate == Decimal_str(net.win_rate)
    assert orm.gross_max_drawdown == Decimal_str(gross.max_drawdown)


def test_to_metrics_orm_inf_calmar_to_none() -> None:
    """无回撤 calmar=inf → ORM 列 None(Numeric 不接受 inf)。"""
    prices = pd.Series([100.0, 101.0, 102.0]).pct_change().fillna(0.0)
    gross = compute_risk_metrics(prices, _zero(n=3))
    assert math.isinf(gross.calmar_ratio)
    orm = to_metrics_orm(uuid.uuid4(), gross, gross)
    assert orm.gross_calmar_ratio is None
    assert orm.net_calmar_ratio is None


def Decimal_str(x: float) -> object:
    """复刻 ``_to_dec`` 的有限值路径,供断言对照。"""
    from decimal import Decimal

    return Decimal(str(float(x)))
