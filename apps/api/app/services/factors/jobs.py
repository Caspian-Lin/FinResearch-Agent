"""Factor worker jobs — async compute / quantile / sensitivity (FRA-57).

把 FRA-56 的三类同步计算(批量因子计算、分层回测、因子敏感性网格)包成可异
步执行的 *job*:`run_id → pending → running → success/failed`。状态机复用 FRA-37
``execute_backtest_run`` 的同一套(``BacktestRun.status`` + ``error_message``),结果
序列化进 FRA-57 新增的 ``BacktestRun.result_json`` —— 这三类任务的输出(行数 /
分层净值序列 / 敏感性 summary)没有专用表,挂在 run 行上即可,``GET /factors/jobs``
一次读回。worker ``worker.tasks.factor`` 仅作 RQ 入口薄封装。

防前视不变:全部复用 FRA-27 ``load_prices``(无 forward-fill)+ FRA-49/50 滚动窗口因
子 + FRA-53 分层引擎 ``shift(1)`` 边界 + FRA-34 指标,本层不引入新口径。

preflight(FRA-43 模式):数据不足 / 未知因子等让 ``load_prices`` / 计算抛
``ValueError`` → run 标 ``failed`` + ``error_message`` 记原因(re-raise 供 RQ 记
``exc_info``),前端轮询即见失败原因,不卡在 running。
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy.orm import object_session

from app.db.session import SessionLocal
from app.models.backtest import BacktestRun
from app.services.backtest.prices import load_prices
from app.services.backtest.sensitivity import (
    factor_sensitivity_configs,
    run_sweep,
    summarize_sweep,
)
from app.services.backtest.types import BacktestConfig, PriceField, RebalanceFreq
from app.services.factors.quantile import QuantileBacktester
from app.services.factors.service import FACTOR_REGISTRY, compute_and_store_factors

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 共享状态机
# ---------------------------------------------------------------------------


def _run_factor_job(
    run_id: str,
    *,
    expected_kind: str,
    compute: Callable[[BacktestRun], dict[str, Any]],
) -> dict[str, Any]:
    """执行一个 factor job 并维护状态机(pending → running → success/failed)。

    仿 :func:`app.services.backtest.execution.execute_backtest_run`:开 session →
    置 running → 调 ``compute(run)`` 得结果 dict → 置 success + 写 ``result_json``;
    任一异常 rollback 后重读 run 置 failed + ``error_message``(≤500 字符)再 re-raise。

    Args:
        run_id: ``BacktestRun`` UUID 字符串(RQ 序列化友好)。
        expected_kind: 期望的 ``run_kind``,不匹配则 failed(防 worker 误调度)。
        compute: 业务回调,接收 run、返回可 JSON 序列化的结果 dict(写入 ``result_json``)。
    """
    rid = uuid.UUID(str(run_id))
    db = SessionLocal()
    try:
        run = db.get(BacktestRun, rid)
        if run is None:
            raise ValueError(f"factor job run {rid} not found")
        if run.run_kind != expected_kind:
            raise ValueError(f"run {rid} run_kind={run.run_kind!r}, expected {expected_kind!r}")

        # pending → running
        run.status = "running"
        run.error_message = None
        db.commit()

        result = compute(run)

        run.status = "success"
        run.result_json = result
        db.commit()

        logger.info("factor job run_id=%s kind=%s status=success", rid, expected_kind)
        return {
            "run_id": str(rid),
            "run_kind": expected_kind,
            "status": "success",
            "result": result,
        }
    except Exception as exc:
        db.rollback()
        # 失败:重读 run(rollback 后实例 expired),记 failed + 错误摘要。
        run = db.get(BacktestRun, rid)
        if run is not None:
            run.status = "failed"
            run.error_message = str(exc)[:500]
            db.commit()
        logger.exception("factor job run_id=%s kind=%s failed", rid, expected_kind)
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 序列化(与 FRA-56 api ``_ts_points`` 同形,service 层不 import api 避免循环)
# ---------------------------------------------------------------------------


def _ts_points(series: pd.Series) -> list[dict[str, Any]]:
    """时序 Series → ``[{time, value}]``(非 NaN,按 index 升序,ISO 字符串)。"""
    clean = series.dropna().sort_index()
    return [{"time": pd.Timestamp(t).isoformat(), "value": float(v)} for t, v in clean.items()]


# ---------------------------------------------------------------------------
# 三类 job
# ---------------------------------------------------------------------------


def execute_factor_compute(run_id: str) -> dict[str, Any]:
    """批量因子计算:``load_prices → compute_and_store_factors`` → 行数写 ``result_json``。

    ``run.config_json`` 需含 ``universe / source / start / end / price_field /
    factor_names``(FRA-56 ``FactorComputeRequest`` 形状)。
    """
    return _run_factor_job(
        run_id,
        expected_kind="factor_compute",
        compute=_compute_factor_values,
    )


def _compute_factor_values(run: BacktestRun) -> dict[str, Any]:
    cfg = dict(run.config_json)
    db = object_session(run)
    assert db is not None  # run 由 _run_factor_job 的 session 加载,必绑定
    rows = compute_and_store_factors(
        db,
        universe=[uuid.UUID(str(u)) for u in cfg["universe"]],
        source=str(cfg["source"]),
        start=date.fromisoformat(str(cfg["start"])),
        end=date.fromisoformat(str(cfg["end"])),
        price_field=PriceField(str(cfg.get("price_field", "adjusted"))),
        factor_names=list(cfg["factor_names"]),
    )
    return {"rows_written": rows, "factor_names": list(cfg["factor_names"])}


def execute_factor_quantile(run_id: str) -> dict[str, Any]:
    """分层回测:``load_prices → 因子 → QuantileBacktester.run`` → 分层净值序列写 ``result_json``。

    ``run.config_json`` 需含 ``universe / source / start / end / price_field /
    factor_name / n_quantiles``(FRA-56 ``QuantileBacktestRequest`` 形状)。
    """
    return _run_factor_job(
        run_id,
        expected_kind="factor_quantile",
        compute=_run_quantile_backtest,
    )


def _run_quantile_backtest(run: BacktestRun) -> dict[str, Any]:
    cfg = dict(run.config_json)
    db = object_session(run)
    assert db is not None
    universe = [uuid.UUID(str(u)) for u in cfg["universe"]]
    prices = load_prices(
        db=db,
        universe=universe,
        source=str(cfg["source"]),
        start=date.fromisoformat(str(cfg["start"])),
        end=date.fromisoformat(str(cfg["end"])),
        price_field=PriceField(str(cfg.get("price_field", "adjusted"))),
    )
    factor_name = str(cfg["factor_name"])
    fn = FACTOR_REGISTRY.get(factor_name)
    if fn is None:
        raise ValueError(f"unknown factor {factor_name!r}; registered: {sorted(FACTOR_REGISTRY)}")
    n_quantiles = int(cfg.get("n_quantiles", 5))
    result = QuantileBacktester().run(fn(prices), prices, n_quantiles)
    return {
        "quantile_equity": {
            str(col): _ts_points(result.quantile_equity[col])
            for col in result.quantile_equity.columns
        },
        "top_minus_bottom": _ts_points(result.top_minus_bottom),
        "monotonicity": float(result.monotonicity),
    }


def execute_factor_sweep(run_id: str) -> dict[str, Any]:
    """因子敏感性网格:``factor_sensitivity_configs → run_sweep → summarize_sweep``。

    summary(metric_table + param_impacts + best/worst net sharpe)写 ``result_json``;
    与 FRA-56 同步 ``/sensitivity`` 同形(纯计算,不落子 run —— 异步版只是把同一计算
    搬到后台,结果以 summary 形式给前端轮询)。

    ``run.config_json`` 需含 FRA-56 ``SensitivityRequest`` 形状。
    """
    return _run_factor_job(
        run_id,
        expected_kind="factor_sweep",
        compute=_run_sensitivity_sweep,
    )


def _run_sensitivity_sweep(run: BacktestRun) -> dict[str, Any]:
    cfg = dict(run.config_json)
    db = object_session(run)
    assert db is not None
    universe = [uuid.UUID(str(u)) for u in cfg["universe"]]
    prices = load_prices(
        db=db,
        universe=universe,
        source=str(cfg["source"]),
        start=date.fromisoformat(str(cfg["start"])),
        end=date.fromisoformat(str(cfg["end"])),
        price_field=PriceField(str(cfg.get("price_field", "adjusted"))),
    )
    base = BacktestConfig(
        universe=tuple(str(u) for u in universe),
        start=date.fromisoformat(str(cfg["start"])),
        end=date.fromisoformat(str(cfg["end"])),
        strategy_name="factor",
        price_field=PriceField(str(cfg.get("price_field", "adjusted"))),
        rebalance=RebalanceFreq.DAILY,
    )
    windows = cfg.get("windows")
    configs = factor_sensitivity_configs(
        base,
        factors=list(cfg["factors"]),
        windows=dict(windows) if windows is not None else None,
        top_ks=list(cfg.get("top_ks", [1, 3])),
        quantiles=list(cfg.get("quantiles", [])),
        n_quantiles=int(cfg.get("n_quantiles", 5)),
        rebalances=list(cfg.get("rebalances", ["daily", "weekly", "monthly"])),
        cost_bands=list(cfg.get("cost_bands", [0.0, 5.0, 10.0, 25.0])),
    )
    points = run_sweep(prices, configs)
    summary = summarize_sweep(points)
    return {
        "metric_table": list(summary.metric_table),
        "param_impacts": [dataclasses.asdict(i) for i in summary.param_impacts],
        "highly_sensitive": summary.highly_sensitive,
        "best_net_sharpe": summary.best_net_sharpe,
        "worst_net_sharpe": summary.worst_net_sharpe,
    }
