"""run_backtest_job RQ task (FRA-37) — thin wrapper.

Core execution lives in ``app.services.backtest.execution.execute_backtest_run`` so
the API/service layer and tests can call it without importing the worker package.
This module is the RQ entrypoint: the worker resolves it by dotted path
``worker.tasks.backtest.run_backtest_job``.

Note: ``app`` is the apps/api package (a uv workspace member). The worker imports
it at runtime — same pattern as ``worker/tasks/ohlcv.py``.
"""

from __future__ import annotations

from typing import Any

from app.services.backtest.execution import execute_backtest_run


def run_backtest_job(run_id: str) -> dict[str, Any]:
    """RQ entrypoint for backtest execution; delegates to the service layer.

    Args:
        run_id: ``BacktestRun`` UUID 字符串(RQ 序列化友好)。

    Returns / Raises: 透传 ``execute_backtest_run``(成功返回结果摘要;失败时 run
        置 failed + error_message 后 re-raise,RQ 记 exc_info)。
    """
    return execute_backtest_run(run_id)
