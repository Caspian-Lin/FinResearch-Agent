"""Backtest execution — run_id → persisted run (FRA-37).

核心执行逻辑:读 ``backtest_run.config_json`` → 价格读取 → 策略 → 引擎 →
指标 → benchmark → 持久化(equity_curve + metrics),状态 ``pending → running →
success/failed``。放在 service 层(而非 worker 包)以便 API 层与测试直接调用,
worker ``run_backtest_job`` 仅作 RQ 入口薄封装。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.db.session import SessionLocal
from app.models.backtest import BacktestRun
from app.services.backtest.benchmark import (
    compute_benchmark_comparison,
    load_benchmark_prices,
)
from app.services.backtest.engine import run_backtest
from app.services.backtest.metrics import compute_result_metrics, to_metrics_orm
from app.services.backtest.persistence import build_equity_curve_points
from app.services.backtest.prices import load_prices
from app.services.backtest.strategies.registry import get_strategy
from app.services.backtest.types import BacktestConfig, PriceField, RebalanceFreq

logger = logging.getLogger(__name__)


def execute_backtest_run(run_id: str) -> dict[str, Any]:
    """执行一次回测并持久化结果(equity_curve + metrics)。

    可直接调用(不依赖 HTTP / RQ),亦可由 ``worker.tasks.backtest.run_backtest_job``
    薄封装后经 RQ 调度。

    Args:
        run_id: ``BacktestRun`` UUID 字符串(RQ 序列化友好)。

    Returns:
        结果摘要 (``run_id`` / ``status`` / ``equity_points`` / ``benchmark``)。

    Raises:
        ValueError: run 不存在 / config_json 非法 / 策略未知 / 数据不足。失败时
            ``run.status='failed'`` + ``error_message`` 记录,然后 re-raise(RQ 记
            ``exc_info``)。
    """
    rid = uuid.UUID(str(run_id))
    db = SessionLocal()
    try:
        run = db.get(BacktestRun, rid)
        if run is None:
            raise ValueError(f"backtest run {rid} not found")

        # pending → running
        run.status = "running"
        run.error_message = None
        db.commit()

        config = _config_from_run(run)

        prices = load_prices(
            db=db,
            universe=tuple(uuid.UUID(u) for u in config.universe),
            source="yfinance",
            start=config.start,
            end=config.end,
            price_field=config.price_field,
        )

        strategy = get_strategy(config.strategy_name, config.strategy_params)
        result = run_backtest(prices, strategy, config)

        # benchmark(可选):价格 + 对比曲线 + 日收益(供 metrics 的 Beta/Correlation)。
        comparison = None
        benchmark_returns = None
        if run.benchmark_asset_id is not None:
            bench_prices = load_benchmark_prices(
                db=db,
                benchmark_asset_id=run.benchmark_asset_id,
                start=config.start,
                end=config.end,
                price_field=config.price_field,
            )
            comparison = compute_benchmark_comparison(result, bench_prices)
            benchmark_returns = bench_prices.iloc[:, 0].pct_change().fillna(0.0)

        # 指标(gross + net)+ 权益曲线(strategy + benchmark)入库。
        gross, net = compute_result_metrics(result, benchmark_returns)
        db.add(to_metrics_orm(rid, gross, net))
        db.add_all(build_equity_curve_points(rid, result, comparison))
        # 注:trades 入库(engine Trade 的 weight-delta → ORM Trade 的
        # quantity/price/cost)留待后续 issue —— schema 不直接对应,转换需额外设计。

        run.status = "success"
        db.commit()

        logger.info(
            "execute_backtest_run run_id=%s status=success points=%d",
            rid,
            len(result.equity_curve),
        )
        return {
            "run_id": str(rid),
            "status": "success",
            "equity_points": len(result.equity_curve),
            "benchmark": run.benchmark_asset_id is not None,
        }
    except Exception as exc:
        db.rollback()
        # 失败:重读 run(rollback 后实例 expired),记 failed + 错误摘要。
        run = db.get(BacktestRun, rid)
        if run is not None:
            run.status = "failed"
            run.error_message = str(exc)[:500]
            db.commit()
        logger.exception("execute_backtest_run run_id=%s failed", rid)
        raise
    finally:
        db.close()


def _config_from_run(run: BacktestRun) -> BacktestConfig:
    """从 ``BacktestRun.config_json`` + 列重建 ``BacktestConfig``。

    ``universe`` / 策略名 / 参数 / 成本来自 ``config_json``;``start`` / ``end``
    来自 ``run.start_date`` / ``end_date``(可复现参数快照)。
    """
    cfg: dict[str, Any] = dict(run.config_json)
    return BacktestConfig(
        universe=tuple(cfg.get("universe", ())),
        start=run.start_date,
        end=run.end_date,
        strategy_name=str(cfg.get("strategy_name", "")),
        initial_capital=float(cfg.get("initial_capital", 100_000.0)),
        cost_bps=float(cfg.get("cost_bps", 0.0)),
        rebalance=RebalanceFreq(str(cfg.get("rebalance", "daily"))),
        price_field=PriceField(run.price_field),
        benchmark=str(run.benchmark_asset_id) if run.benchmark_asset_id else None,
        strategy_params=dict(cfg.get("strategy_params", {})),
    )
