"""Sentiment comparison backtest execution — run_id → persisted child runs (FRA-71).

把 FRA-71 ``run_comparison`` 包成可异步执行的 *job*:读 parent BacktestRun
(``run_kind="sentiment_comparison"``)→ 加载 prices + sentiment factor → 跑对照
实验 → 为每组(technical / sentiment_tech / 可选 sentiment_only)创建子
BacktestRun 并持久化 metrics + equity_curve + trades。

状态机复用 FRA-70 ``_run_sentiment_job`` 的同一套(parent pending → running →
success/failed),child runs 直接以 ``status="success"`` 创建(结果在内存中算好
后一次性写入)。

防前视不变:sentiment factor 从 ``factor_values`` 读取(FRA-69 已映射到 >=
``published_at`` 的交易日);引擎统一 ``shift(1)``。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.backtest import BacktestRun
from app.services.backtest.benchmark import (
    compute_benchmark_comparison,
    load_benchmark_prices,
)
from app.services.backtest.comparison import run_comparison
from app.services.backtest.metrics import compute_result_metrics, to_metrics_orm
from app.services.backtest.persistence import build_equity_curve_points, build_trade_points
from app.services.backtest.prices import load_prices
from app.services.backtest.types import BacktestConfig, BacktestResult, PriceField, RebalanceFreq
from app.services.factors.service import read_factor_values
from app.services.sentiment.service import SENTIMENT_FACTOR_NAME

logger = logging.getLogger(__name__)


def execute_comparison_run(run_id: str) -> dict[str, Any]:
    """执行 sentiment 对照实验并持久化子 run(pending → running → success/failed)。

    Args:
        run_id: parent ``BacktestRun`` UUID 字符串。
            ``run.config_json`` 需含:
            * ``universe`` / ``start`` / ``end`` / ``initial_capital`` / ``cost_bps``
              / ``rebalance`` / ``price_field`` / ``benchmark``
            * ``model_name`` — sentiment factor 的 source(分类器模型名)
            * ``strategy_params`` — 技术因子 / 窗口 / top_k / mode / threshold / weight
            * ``include_sentiment_only`` — 是否跑 sentiment-only 对照

    Returns:
        结果摘要(parent run_id / status / child_runs 列表)。

    Raises:
        ValueError: run 不存在 / run_kind 不匹配 / sentiment factor 无数据。
    """
    rid = uuid.UUID(str(run_id))
    db = SessionLocal()
    try:
        run = db.get(BacktestRun, rid)
        if run is None:
            raise ValueError(f"comparison run {rid} not found")
        if run.run_kind != "sentiment_comparison":
            raise ValueError(
                f"run {rid} run_kind={run.run_kind!r}, expected 'sentiment_comparison'"
            )

        # pending → running
        run.status = "running"
        run.error_message = None
        db.commit()

        cfg = dict(run.config_json)
        config = _config_from_dict(cfg, run)

        # 加载价格(三组共用)
        universe_uuids = [uuid.UUID(str(a)) for a in cfg["universe"]]
        prices = load_prices(
            db=db,
            universe=tuple(universe_uuids),
            source="yfinance",
            start=config.start,
            end=config.end,
            price_field=config.price_field,
        )

        # 加载 sentiment factor(从 factor_values 表)
        model_name = str(cfg["model_name"])
        sentiment_frame = read_factor_values(
            db,
            asset_ids=universe_uuids,
            factor_name=SENTIMENT_FACTOR_NAME,
            source=model_name,
            start=config.start,
            end=config.end,
        )
        if sentiment_frame.shape[0] == 0 or sentiment_frame.shape[1] == 0:
            raise ValueError(
                f"no sentiment_score factor data found for model={model_name!r} "
                f"in [{config.start}, {config.end}]; run FRA-69 sentiment factor "
                f"compute first"
            )

        # 跑对照实验(纯计算)
        comparison = run_comparison(
            prices,
            sentiment_frame,
            config,
            strategy_params=cfg.get("strategy_params", {}),
        )

        # benchmark(可选,三组共用同一基准)
        benchmark_returns = None
        if run.benchmark_asset_id is not None:
            bench_prices = load_benchmark_prices(
                db=db,
                benchmark_asset_id=run.benchmark_asset_id,
                start=config.start,
                end=config.end,
                price_field=config.price_field,
            )
            benchmark_returns = bench_prices.iloc[:, 0].pct_change().fillna(0.0)

        # 为每组创建子 BacktestRun + 持久化结果
        child_ids: list[str] = []
        groups: list[tuple[str, str, BacktestResult]] = [
            ("technical", "Technical-only", comparison.technical),
            ("sentiment_tech", "Technical + Sentiment", comparison.sentiment_tech),
        ]
        if comparison.sentiment_only is not None:
            groups.append(("sentiment_only", "Sentiment-only", comparison.sentiment_only))

        for role, label, result in groups:
            child_id = _persist_child_run(
                db=db,
                parent=run,
                config=config,
                prices=prices,
                result=result,
                benchmark_returns=benchmark_returns,
                role=role,
                label=label,
            )
            child_ids.append(child_id)

        # parent 置 success + 写 result_json(子 run IDs)
        run.status = "success"
        run.result_json = {
            "child_runs": child_ids,
            "groups": [g[0] for g in groups],
        }
        db.commit()

        logger.info(
            "execute_comparison_run run_id=%s status=success children=%d",
            rid,
            len(child_ids),
        )
        return {
            "run_id": str(rid),
            "status": "success",
            "child_runs": child_ids,
        }
    except Exception as exc:
        db.rollback()
        run = db.get(BacktestRun, rid)
        if run is not None:
            run.status = "failed"
            run.error_message = str(exc)[:500]
            db.commit()
        logger.exception("execute_comparison_run run_id=%s failed", rid)
        raise
    finally:
        db.close()


def _persist_child_run(
    *,
    db: Session,
    parent: BacktestRun,
    config: BacktestConfig,
    prices: pd.DataFrame,
    result: BacktestResult,
    benchmark_returns: pd.Series | None,
    role: str,
    label: str,
) -> str:
    """创建一个子 BacktestRun 并持久化 metrics + equity + trades。

    Returns:
        子 run 的 UUID 字符串。
    """
    child = BacktestRun(
        user_id=parent.user_id,
        name=f"{parent.name} [{label}]",
        strategy_type=f"sentiment_comparison_{role}",
        config_json={
            **dict(parent.config_json),
            "comparison_role": role,
            "comparison_label": label,
            "comparison_parent": str(parent.id),
        },
        benchmark_asset_id=parent.benchmark_asset_id,
        start_date=parent.start_date,
        end_date=parent.end_date,
        price_field=parent.price_field,
        status="success",
        run_kind="backtest",
    )
    db.add(child)
    db.flush()  # 获取 child.id

    # benchmark comparison(可选)
    comparison_obj = None
    if parent.benchmark_asset_id is not None:
        bench_prices = load_benchmark_prices(
            db=db,
            benchmark_asset_id=parent.benchmark_asset_id,
            start=config.start,
            end=config.end,
            price_field=config.price_field,
        )
        comparison_obj = compute_benchmark_comparison(result, bench_prices)

    # metrics(gross + net)
    gross, net = compute_result_metrics(result, benchmark_returns)
    db.add(to_metrics_orm(child.id, gross, net))

    # equity curve + trades
    db.add_all(build_equity_curve_points(child.id, result, comparison_obj))
    db.add_all(build_trade_points(child.id, result, prices, config))

    return str(child.id)


def _config_from_dict(cfg: dict[str, Any], run: BacktestRun) -> BacktestConfig:
    """从 ``config_json`` + run 列重建 ``BacktestConfig``(同 execution._config_from_run)。"""
    return BacktestConfig(
        universe=tuple(cfg.get("universe", ())),
        start=run.start_date,
        end=run.end_date,
        strategy_name="sentiment_comparison",
        initial_capital=float(cfg.get("initial_capital", 100_000.0)),
        cost_bps=float(cfg.get("cost_bps", 0.0)),
        rebalance=RebalanceFreq(str(cfg.get("rebalance", "daily"))),
        price_field=PriceField(run.price_field),
        benchmark=str(run.benchmark_asset_id) if run.benchmark_asset_id else None,
        strategy_params=dict(cfg.get("strategy_params", {})),
    )
