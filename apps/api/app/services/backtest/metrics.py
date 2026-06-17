"""Risk / return metrics — §11.2 nine indicators, gross + net (FRA-34).

把一条日收益序列 + 换手序列(可选 benchmark)换算成 §11.2 全部 9 个指标,并用
``compute_result_metrics`` 对回测结果的 gross / net 双口径各算一套,支撑 §11.3
第 5 条「成本前后对比」。``to_metrics_orm`` 把双口径指标映射到 FRA-26
``backtest_metrics`` 表(18 列 Decimal),便于 API 层一行写入(实际 ``session.add``
/ commit 由回测触发 API issue 负责,本模块不碰 DB)。

年化约定(§11.2)
-----------------
* **收益**:算术年化 ``mean(daily) × periods_per_year``(默认 252)。
* **波动**:``std(daily, ddof=1) × sqrt(periods_per_year)``。
* **Sharpe**:``((mean − rf/ppy) / std) × sqrt(ppy)``,等价
  ``(annual_return − rf) / volatility``;``risk_free_rate`` 为**年化**无风险利率,默认 0。
* **turnover**:平均日换手 × ``periods_per_year``(年化换手率);gross / net 共用同一
  换手序列(持仓相同,换手与成本口径无关)。
* **Beta / Correlation**:相对 benchmark 的日频协方差比 / 皮尔逊相关;无 benchmark
  或样本不足 → ``0.0``。

防前视:所有指标仅消费截至当日的已实现收益序列,不引用未来价格。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import numpy as np
import pandas as pd

from app.models.backtest import BacktestMetrics as BacktestMetricsORM
from app.services.backtest.types import BacktestMetrics, BacktestResult


def compute_risk_metrics(
    returns: pd.Series,
    turnover: pd.Series,
    benchmark_returns: pd.Series | None = None,
    *,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> BacktestMetrics:
    """单口径:从一条日收益序列算 §11.2 全部 9 个指标(纯计算,不碰 DB)。

    与口径正交:传入 gross 收益序列得 gross 指标,net 序列得 net 指标——成本前后
    对比只需调用两次。对 ``compute_result_metrics`` 而言,gross 用
    ``BacktestResult.gross_returns``、net 用 ``daily_returns``。

    Parameters
    ----------
    returns:
        日收益序列(tz-aware UTC midnight 索引或任意单调索引均可,本函数不依赖
        绝对日期)。首日建仓 0 收益保留(正常交易日,计入 win_rate 分母)。
    turnover:
        与 ``returns`` 同索引的每日单边换手(|Δholdings| 之和);年化为
        ``mean × periods_per_year``。
    benchmark_returns:
        可选 benchmark 日收益序列(如 QQQ/SPY 的 ``pct_change``);提供则算
        Beta / Correlation,否则二者为 ``0.0``。
    risk_free_rate:
        **年化**无风险利率,默认 0;日化为 ``rf / periods_per_year`` 后从每日收益
        扣除再算 Sharpe。
    periods_per_year:
        年交易日数,默认 252。

    Returns
    -------
    BacktestMetrics
        9 个指标的单一口径集合。退化输入(空 / 全 NaN)→ 全 0;无回撤 →
        ``calmar_ratio = inf``(ORM 映射时转 ``None``)。

    Notes
    -----
    * ``max_drawdown`` 以 ``equity = (1 + ret).cumprod()`` 的累计最大值为基准,
      恒 ≤ 0。
    * ``win_rate`` = ``P(ret > 0)``,含 0 收益日计入分母。
    * Beta = ``cov(r, b) / var(b)``;Correlation = Pearson ``r``;二者在共同有效
      窗口上计算,benchmark 方差为 0 或样本 < 2 → ``0.0``。
    """
    clean = returns.astype("float64").dropna()
    if clean.empty:
        return _zero_metrics()

    ppy = periods_per_year
    mean_ret = float(clean.mean())
    std_ret = float(clean.std(ddof=1)) if len(clean) >= 2 else 0.0

    annual_return = mean_ret * ppy
    volatility = std_ret * float(np.sqrt(ppy))
    # Sharpe = (mean − rf_daily) / std × sqrt(ppy) == (annual_return − rf) / vol。
    if std_ret > 0.0:
        excess_daily = mean_ret - risk_free_rate / ppy
        sharpe_ratio = (excess_daily / std_ret) * float(np.sqrt(ppy))
    else:
        sharpe_ratio = 0.0

    # Max drawdown:equity = (1 + ret).cumprod()(隐含首值 1),恒 ≤ 0。
    equity = (1.0 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    calmar_ratio = annual_return / abs(max_drawdown) if max_drawdown < 0.0 else float("inf")

    # Turnover:平均日换手年化。
    turnover_clean = turnover.astype("float64").reindex(clean.index).dropna()
    turnover_annual = float(turnover_clean.mean()) * ppy if not turnover_clean.empty else 0.0

    # Win rate:正收益日占比。
    win_rate = float((clean > 0).mean())

    # Beta / Correlation:相对 benchmark。
    beta, correlation = _beta_correlation(clean, benchmark_returns)

    return BacktestMetrics(
        annual_return=annual_return,
        volatility=volatility,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        calmar_ratio=calmar_ratio,
        turnover=turnover_annual,
        win_rate=win_rate,
        beta=beta,
        correlation=correlation,
    )


def _beta_correlation(
    returns: pd.Series, benchmark_returns: pd.Series | None
) -> tuple[float, float]:
    """日频 Beta = cov(r, b)/var(b);Correlation = Pearson r。

    无 benchmark、对齐后样本 < 2、或 benchmark 方差 ≤ 0 → ``(0.0, 0.0)``
    (避免除零;样本不足时 Beta/Correlation 无意义)。
    """
    if benchmark_returns is None or benchmark_returns.empty:
        return 0.0, 0.0
    aligned = pd.concat(
        [returns.rename("r"), benchmark_returns.astype("float64").rename("b")],
        axis=1,
    ).dropna()
    if len(aligned) < 2:
        return 0.0, 0.0
    bench_var = float(aligned["b"].var(ddof=1))
    if bench_var <= 0.0:
        return 0.0, 0.0
    beta = float(aligned["r"].cov(aligned["b"]) / bench_var)
    correlation = float(aligned["r"].corr(aligned["b"]))
    return beta, correlation


def compute_result_metrics(
    result: BacktestResult,
    benchmark_returns: pd.Series | None = None,
    *,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> tuple[BacktestMetrics, BacktestMetrics]:
    """对 ``BacktestResult`` 的 gross / net 双口径各算一套 §11.2 指标。

    Args:
        result: 已完成的回测结果;``gross_returns`` → gross 指标,
            ``daily_returns``(net)→ net 指标,``turnover`` 两套共用。
        benchmark_returns: 可选 benchmark 日收益序列(Beta / Correlation 基准)。

    Returns:
        ``(gross_metrics, net_metrics)``——成本前 / 成本后两组,支撑 §11.3 第 5 条
        「成本前后对比」。``cost_bps == 0`` 时两组数值一致(浮点)。
    """
    gross = compute_risk_metrics(
        result.gross_returns,
        turnover=result.turnover,
        benchmark_returns=benchmark_returns,
        risk_free_rate=risk_free_rate,
        periods_per_year=periods_per_year,
    )
    net = compute_risk_metrics(
        result.daily_returns,
        turnover=result.turnover,
        benchmark_returns=benchmark_returns,
        risk_free_rate=risk_free_rate,
        periods_per_year=periods_per_year,
    )
    return gross, net


def to_metrics_orm(
    run_id: uuid.UUID,
    gross: BacktestMetrics,
    net: BacktestMetrics,
) -> BacktestMetricsORM:
    """映射 gross/net 双口径 → FRA-26 ``backtest_metrics`` ORM(18 列 Decimal)。

    纯映射,不触碰 session;实际 ``session.add`` / commit 由回测触发 API issue
    在创建 ``BacktestRun`` 时完成。``inf`` / ``nan`` 指标(如无回撤的 calmar)转为
    ``None``——Postgres ``Numeric`` 列不接受非有限值。
    """
    return BacktestMetricsORM(
        backtest_run_id=run_id,
        gross_annual_return=_to_dec(gross.annual_return),
        gross_volatility=_to_dec(gross.volatility),
        gross_sharpe_ratio=_to_dec(gross.sharpe_ratio),
        gross_max_drawdown=_to_dec(gross.max_drawdown),
        gross_calmar_ratio=_to_dec(gross.calmar_ratio),
        gross_turnover=_to_dec(gross.turnover),
        gross_win_rate=_to_dec(gross.win_rate),
        gross_beta=_to_dec(gross.beta),
        gross_correlation=_to_dec(gross.correlation),
        net_annual_return=_to_dec(net.annual_return),
        net_volatility=_to_dec(net.volatility),
        net_sharpe_ratio=_to_dec(net.sharpe_ratio),
        net_max_drawdown=_to_dec(net.max_drawdown),
        net_calmar_ratio=_to_dec(net.calmar_ratio),
        net_turnover=_to_dec(net.turnover),
        net_win_rate=_to_dec(net.win_rate),
        net_beta=_to_dec(net.beta),
        net_correlation=_to_dec(net.correlation),
    )


def _to_dec(x: float) -> Decimal | None:
    """float → Decimal(可入库);``inf`` / ``nan`` → ``None``(Numeric 列不接受)。"""
    f = float(x)
    if not np.isfinite(f):
        return None
    return Decimal(str(f))


def _zero_metrics() -> BacktestMetrics:
    """退化(空 / 全 NaN 输入)指标集合:全 0,避免 NaN 污染下游。"""
    return BacktestMetrics(
        annual_return=0.0,
        volatility=0.0,
        sharpe_ratio=0.0,
        max_drawdown=0.0,
        calmar_ratio=0.0,
        turnover=0.0,
        win_rate=0.0,
        beta=0.0,
        correlation=0.0,
    )
