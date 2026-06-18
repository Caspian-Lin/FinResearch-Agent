"""Parameter / cost sensitivity sweep — Week 2 MVP (FRA-35, §7.2 / §11.3).

对可参数化策略(MA fast/slow、Momentum lookback/top-k/rebalance)在小网格上做
sweep,每个策略点再叠加多档交易成本(bps),为每个 (参数, cost) 组合算 gross/net
双口径指标,汇总成「参数 → 指标」表并标注结果是否高度依赖单一参数。

Week 2 范围(见 ``docs/backtesting-methodology.md`` §Sensitivity Analysis):

* 只跑小规模人工网格,不做超参搜索 / 优化(Week 3);
* 不做因子 IC / 分层回测 / 显著性统计(Week 3);
* 产出表格 / JSON,不要求前端热力图。

分层
----

* :func:`ma_crossover_configs` / :func:`momentum_configs`:从一份 base
  ``BacktestConfig`` 展开成网格(每个组合一份 frozen config)。
* :func:`run_sweep`:对同一份 ``prices`` 跑所有 config → ``list[SweepPoint]``
  (纯计算,不碰 DB,易单测)。
* :func:`summarize_sweep`:把 points 汇总成「参数 → 指标」表 + 每维度影响度量,
  标注是否高度依赖单一参数。
* :func:`persist_sweep`:把每个 point 写成一个 ``BacktestRun(run_kind='sensitivity')``
  + 1:1 ``BacktestMetrics``,``config_json`` 内嵌完整 sweep 网格(可复现)。

防前视:sweep 复用 FRA-28 引擎 + FRA-34 指标,所有指标仅消费截至当日已实现收益。
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from collections.abc import Sequence
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.models.backtest import RUN_KINDS, BacktestRun
from app.services.backtest.engine import run_backtest
from app.services.backtest.metrics import compute_result_metrics, to_metrics_orm
from app.services.backtest.strategies.registry import get_strategy
from app.services.backtest.types import BacktestConfig, BacktestMetrics, RebalanceFreq

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 默认网格(issue 要求的最低规模;调用方可覆盖)
# ---------------------------------------------------------------------------

#: 交易成本档(§11.3 第 5 条「成本前后对比」+ §7.2 成本敏感性)。单位 bps,单边。
DEFAULT_COST_BANDS: tuple[float, ...] = (0.0, 5.0, 10.0, 25.0)

#: MA 快均线档(``fast < slow`` 由 :func:`ma_crossover_configs` 过滤)。
DEFAULT_MA_FASTS: tuple[int, ...] = (5, 10)
#: MA 慢均线档。
DEFAULT_MA_SLOWS: tuple[int, ...] = (20, 50)

#: Momentum 回看周期档(约 1M / 3M)。
DEFAULT_MOMENTUM_LOOKBACKS: tuple[int, ...] = (21, 63)
#: Momentum 做强资产数档。
DEFAULT_MOMENTUM_TOP_KS: tuple[int, ...] = (1, 3)
#: Momentum rebalance 频率档(覆盖 issue 的「rebalance 至少一个小网格」)。
DEFAULT_MOMENTUM_REBALANCES: tuple[str, ...] = ("daily", "monthly")


# ---------------------------------------------------------------------------
# dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class SweepPoint:
    """网格中一个 (策略参数, 成本) 组合的 gross/net 双口径指标。

    ``params`` 仅含策略超参(fast/slow 或 lookback/top_k),``cost_bps`` 单独
    成维度 —— 这样 :func:`summarize_sweep` 能分别度量「策略参数影响」与「成本影响」。
    """

    params: dict[str, Any]
    cost_bps: float
    gross: BacktestMetrics
    net: BacktestMetrics


@dataclasses.dataclass(frozen=True, slots=True)
class ParamImpact:
    """单维度(strategy 参数或 ``cost_bps``)对 net Sharpe 的影响度量。

    采用 *normalized range*:对该维度的每个取值,取落在该值上的所有点的 net Sharpe
    均值(组均值),再算 ``(max 组均值 − min 组均值) / |总体均值|``。分母用总体
    |mean| 归一化,使不同策略间可比;|mean| 极小时用 ``_MEAN_FLOOR`` 保护。
    ``high_impact`` 在 normalized range 超过 ``cv_threshold``(默认 0.5)时置真。
    """

    param: str
    normalized_range: float
    absolute_range: float
    high_impact: bool


@dataclasses.dataclass(frozen=True, slots=True)
class SweepSummary:
    """sweep 汇总:指标表 + 每维度影响 + 整体判断。"""

    metric_table: list[dict[str, Any]]
    param_impacts: list[ParamImpact]
    highly_sensitive: bool
    best_net_sharpe: float | None
    worst_net_sharpe: float | None


# ---------------------------------------------------------------------------
# 网格展开
# ---------------------------------------------------------------------------


def ma_crossover_configs(
    base: BacktestConfig,
    *,
    fasts: Sequence[int] = DEFAULT_MA_FASTS,
    slows: Sequence[int] = DEFAULT_MA_SLOWS,
    cost_bands: Sequence[float] = DEFAULT_COST_BANDS,
) -> list[BacktestConfig]:
    """MA crossover 网格:``fast × slow``(过滤 ``fast >= slow``)× ``cost_bands``。

    Args:
        base: 基础 config(universe / start / end / price_field / rebalance 取自它);
            其 ``strategy_name`` 必须为 ``ma_crossover``。
        fasts / slows / cost_bands: 三轴档位(默认满足 issue 的 ≥2×2 + 4 档成本)。

    Raises:
        ValueError: ``base.strategy_name`` 不是 ``ma_crossover``。
    """
    _require_strategy(base, "ma_crossover", "ma_crossover_configs")
    configs: list[BacktestConfig] = []
    for fast in fasts:
        for slow in slows:
            if fast >= slow:
                continue
            for cost in cost_bands:
                configs.append(
                    dataclasses.replace(
                        base,
                        strategy_params={"fast": fast, "slow": slow},
                        cost_bps=float(cost),
                    )
                )
    return configs


def momentum_configs(
    base: BacktestConfig,
    *,
    lookbacks: Sequence[int] = DEFAULT_MOMENTUM_LOOKBACKS,
    top_ks: Sequence[int] = DEFAULT_MOMENTUM_TOP_KS,
    rebalances: Sequence[str] = DEFAULT_MOMENTUM_REBALANCES,
    cost_bands: Sequence[float] = DEFAULT_COST_BANDS,
) -> list[BacktestConfig]:
    """Momentum 网格:``lookback × top_k × rebalance × cost_bands``。

    覆盖 issue 的「lookback / top-k / rebalance 至少一个小网格」—— rebalance 轴
    (daily / monthly)单独成维度,使换仓频率对结果的影响可被度量。

    Raises:
        ValueError: ``base.strategy_name`` 不是 ``momentum``。
    """
    _require_strategy(base, "momentum", "momentum_configs")
    configs: list[BacktestConfig] = []
    for lb in lookbacks:
        for tk in top_ks:
            for rb in rebalances:
                for cost in cost_bands:
                    configs.append(
                        dataclasses.replace(
                            base,
                            strategy_params={"lookback": lb, "top_k": tk},
                            rebalance=RebalanceFreq(rb),
                            cost_bps=float(cost),
                        )
                    )
    return configs


def _require_strategy(base: BacktestConfig, expected: str, fn: str) -> None:
    if base.strategy_name != expected:
        raise ValueError(f"{fn} expects strategy_name={expected!r}, got {base.strategy_name!r}")


# ---------------------------------------------------------------------------
# 纯计算:跑网格 → SweepPoint
# ---------------------------------------------------------------------------


def run_sweep(
    prices: pd.DataFrame,
    configs: Sequence[BacktestConfig],
    *,
    benchmark_returns: pd.Series | None = None,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> list[SweepPoint]:
    """对同一份 ``prices`` 逐 config 跑回测 + 双口径指标(纯计算,不碰 DB)。

    每个 config 的 ``strategy_name`` / ``strategy_params`` / ``cost_bps`` 决定网格点;
    ``benchmark_returns`` 透传给指标(算 Beta / Correlation)。复用 FRA-28 引擎 +
    FRA-34 指标,防前视口径不变。

    Args:
        prices: FRA-25 价格宽表(tz-aware UTC 午夜 index,``str(asset_id)`` 列)。
        configs: 网格点(由 :func:`ma_crossover_configs` / :func:`momentum_configs` 展开)。
        benchmark_returns: 可选 benchmark 日收益(Beta / Correlation 基准)。

    Returns:
        每个 config 一个 :class:`SweepPoint`,顺序与 ``configs`` 一致。
    """
    points: list[SweepPoint] = []
    for cfg in configs:
        strategy = get_strategy(cfg.strategy_name, cfg.strategy_params)
        result = run_backtest(prices, strategy, cfg)
        gross, net = compute_result_metrics(
            result,
            benchmark_returns,
            risk_free_rate=risk_free_rate,
            periods_per_year=periods_per_year,
        )
        points.append(
            SweepPoint(
                params=dict(cfg.strategy_params),
                cost_bps=cfg.cost_bps,
                gross=gross,
                net=net,
            )
        )
    return points


# ---------------------------------------------------------------------------
# 汇总:参数 → 指标表 + 高度依赖判定
# ---------------------------------------------------------------------------

#: net Sharpe 的 normalized-range 阈值;超过即视为该维度「高影响」。
DEFAULT_CV_THRESHOLD = 0.5
#: |总体均值| 的下限,避免分母接近 0 时 normalized range 爆炸。
_MEAN_FLOOR = 1e-6


def summarize_sweep(
    points: Sequence[SweepPoint],
    *,
    cv_threshold: float = DEFAULT_CV_THRESHOLD,
) -> SweepSummary:
    """把 sweep points 汇总成指标表 + 每维度影响 + 整体敏感判断。

    Args:
        points: :func:`run_sweep` 的输出。
        cv_threshold: normalized range 超过此值则该维度判为高影响(默认 0.5)。

    Returns:
        :class:`SweepSummary`:

        * ``metric_table``:每点一行(params + cost_bps + gross/net Sharpe / MaxDD /
          turnover + gross-net 年化收益差),支撑「参数 → 指标」可对比表;
        * ``param_impacts``:每个策略参数维度 + ``cost_bps`` 的 :class:`ParamImpact`;
        * ``highly_sensitive``:任一维度高影响 → 真(即「结果高度依赖单一参数」)。
    """
    metric_table: list[dict[str, Any]] = []
    for p in points:
        metric_table.append(
            {
                "params": dict(p.params),
                "cost_bps": p.cost_bps,
                "gross_sharpe": p.gross.sharpe_ratio,
                "net_sharpe": p.net.sharpe_ratio,
                "gross_max_drawdown": p.gross.max_drawdown,
                "net_max_drawdown": p.net.max_drawdown,
                "turnover": p.net.turnover,
                "gross_net_return_gap": p.gross.annual_return - p.net.annual_return,
            }
        )

    # 维度集:所有策略参数 key + cost_bps。
    param_keys: set[str] = set()
    for p in points:
        param_keys.update(p.params.keys())
    dimensions = sorted(param_keys) + ["cost_bps"]

    impacts = [_param_impact(points, dim, cv_threshold=cv_threshold) for dim in dimensions]

    sharpes = [p.net.sharpe_ratio for p in points]
    highly_sensitive = any(i.high_impact for i in impacts)

    return SweepSummary(
        metric_table=metric_table,
        param_impacts=impacts,
        highly_sensitive=highly_sensitive,
        best_net_sharpe=max(sharpes) if sharpes else None,
        worst_net_sharpe=min(sharpes) if sharpes else None,
    )


def _param_impact(points: Sequence[SweepPoint], dim: str, *, cv_threshold: float) -> ParamImpact:
    """单维度 net Sharpe 的 normalized range(见 :class:`ParamImpact` docstring)。

    纯 Python 实现(不依赖 pandas groupby),避免 stubs / 链式索引的类型噪音。
    """
    groups: dict[Any, list[float]] = {}
    all_sharpes: list[float] = []
    for p in points:
        if dim == "cost_bps":
            key: Any = p.cost_bps
        else:
            key = p.params.get(dim)
            if key is None:
                continue
        groups.setdefault(key, []).append(p.net.sharpe_ratio)
        all_sharpes.append(p.net.sharpe_ratio)

    if not groups:
        return ParamImpact(param=dim, normalized_range=0.0, absolute_range=0.0, high_impact=False)

    means = [sum(v) / len(v) for v in groups.values()]
    abs_range = max(means) - min(means)
    overall_mean = abs(sum(all_sharpes) / len(all_sharpes))
    denom = max(overall_mean, _MEAN_FLOOR)
    norm_range = abs_range / denom
    return ParamImpact(
        param=dim,
        normalized_range=norm_range,
        absolute_range=abs_range,
        high_impact=norm_range > cv_threshold,
    )


# ---------------------------------------------------------------------------
# 入库:每点一个 sensitivity run + 1:1 metrics
# ---------------------------------------------------------------------------


def persist_sweep(
    db: Session,
    *,
    user_id: uuid.UUID,
    base: BacktestConfig,
    strategy_name: str,
    grid: dict[str, Any],
    points: Sequence[SweepPoint],
    name_prefix: str,
    benchmark_asset_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """把每个 :class:`SweepPoint` 写成一个 ``BacktestRun(run_kind='sensitivity')``
    + 1:1 ``BacktestMetrics``,内部 commit。

    每个 run 的 ``config_json`` 内嵌完整 sweep ``grid`` 规格 + 该点的策略参数 / 成本,
    使任一子 run 都能独立复现(§11.3 第 6 条)。指标直接来自 ``points``
    (:func:`run_sweep` 已算好),**不重跑回测** —— sweep 复用同一份 prices,重跑浪费。

    Args:
        db: 已开启的 SQLAlchemy session(本函数末尾 ``commit``)。
        user_id: 归属用户。
        base: sweep 的基础 config(universe / start / end / price_field / rebalance 取自它)。
        strategy_name: ``ma_crossover`` 或 ``momentum``。
        grid: 完整网格规格(写入每个 run 的 ``config_json.sweep.grid``,可复现)。
        points: :func:`run_sweep` 输出。
        name_prefix: run 名称前缀(便于按 sweep 分组 / 清理)。
        benchmark_asset_id: 可选 benchmark 资产(写入 ``run.benchmark_asset_id``)。

    Returns:
        新建的 run id 列表(顺序与 ``points`` 一致)。

    Raises:
        ValueError: ``strategy_name`` 不是 ``ma_crossover`` / ``momentum``。
    """
    if strategy_name not in {"ma_crossover", "momentum"}:
        raise ValueError(f"persist_sweep supports ma_crossover / momentum, got {strategy_name!r}")

    run_ids: list[uuid.UUID] = []
    for p in points:
        cfg_json: dict[str, Any] = {
            "universe": list(base.universe),
            "strategy_name": strategy_name,
            "initial_capital": base.initial_capital,
            "cost_bps": p.cost_bps,
            "rebalance": base.rebalance.value,
            "price_field": base.price_field.value,
            "strategy_params": dict(p.params),
            "sweep": {
                "kind": "parameter_cost_sensitivity",
                "grid": grid,
            },
        }
        run = BacktestRun(
            user_id=user_id,
            name=f"{name_prefix}/{strategy_name}/{_params_tag(p)}",
            strategy_type=strategy_name,
            config_json=cfg_json,
            benchmark_asset_id=benchmark_asset_id,
            start_date=base.start,
            end_date=base.end,
            price_field=base.price_field.value,
            status="success",
            run_kind=RUN_KINDS[1],  # "sensitivity"
        )
        db.add(run)
        db.flush()  # 取 run.id 供 1:1 metrics 引用
        db.add(to_metrics_orm(run.id, p.gross, p.net))
        run_ids.append(run.id)

    db.commit()
    logger.info(
        "persist_sweep strategy=%s runs=%d prefix=%s", strategy_name, len(run_ids), name_prefix
    )
    return run_ids


def _params_tag(p: SweepPoint) -> str:
    """把一个 point 的参数 + 成本压成可读的 run 名称片段(供分组 / 清理)。"""
    parts = [f"{k}={v}" for k, v in sorted(p.params.items())]
    parts.append(f"{p.cost_bps}bps")
    return "_".join(parts)
