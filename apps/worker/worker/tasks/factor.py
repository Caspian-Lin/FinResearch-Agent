"""Factor RQ tasks (FRA-57) — thin wrappers.

核心执行逻辑在 ``app.services.factors.jobs``(service 层,API / 测试可直接调,
免 import worker 包)。本模块是 RQ 入口:worker 按 dotted path
``worker.tasks.factor.run_factor_*_job`` 解析调度。三类 job 共享
``BacktestRun`` 状态机(pending → running → success/failed)+ ``result_json`` +
``error_message``(preflight 数据不足 / 未知因子提前 failed)。

复用 ``backtest`` 队列(``worker/main.py`` 已监听)—— factor 计算与回测同属计算
密集,同一 worker 进程即可,无需独立队列。

Note: ``app`` 是 apps/api 包(uv workspace member);worker 运行时 import,同
``worker/tasks/backtest.py`` / ``ohlcv.py`` 模式。
"""

from __future__ import annotations

from typing import Any

from app.services.factors.jobs import (
    execute_factor_compute,
    execute_factor_quantile,
    execute_factor_sweep,
)


def run_factor_compute_job(run_id: str) -> dict[str, Any]:
    """RQ 入口:批量因子计算 → ``factor_values`` 幂等 upsert。

    Args:
        run_id: ``BacktestRun(run_kind='factor_compute')`` UUID 字符串。

    Returns / Raises: 透传 :func:`execute_factor_compute`(成功返回 status=result
        摘要;失败 run 置 failed + error_message 后 re-raise,RQ 记 exc_info)。
    """
    return execute_factor_compute(run_id)


def run_factor_quantile_job(run_id: str) -> dict[str, Any]:
    """RQ 入口:分层(分位数)回测 → 分层净值序列写 ``result_json``。

    Args:
        run_id: ``BacktestRun(run_kind='factor_quantile')`` UUID 字符串。
    """
    return execute_factor_quantile(run_id)


def run_factor_sweep_job(run_id: str) -> dict[str, Any]:
    """RQ 入口:因子敏感性网格 → summary(metric_table + param_impacts)写 ``result_json``。

    Args:
        run_id: ``BacktestRun(run_kind='factor_sweep')`` UUID 字符串。
    """
    return execute_factor_sweep(run_id)
