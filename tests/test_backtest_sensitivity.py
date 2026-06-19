"""Parameter / cost sensitivity sweep tests (FRA-35).

纯单元(无 DB)覆盖:网格展开(MA/Momentum)、``run_sweep`` 成本单调性、
``summarize_sweep`` 指标表 + 高度依赖判定。DB 集成覆盖 ``persist_sweep`` 入库
(``run_kind='sensitivity'`` + 1:1 metrics + config_json 含完整网格)。
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import date

import numpy as np
import pandas as pd
import pytest
from app.db.session import SessionLocal
from app.models.backtest import BacktestMetrics, BacktestRun
from app.models.user import User
from app.services.backtest.sensitivity import (
    DEFAULT_COST_BANDS,
    SweepPoint,
    ma_crossover_configs,
    momentum_configs,
    persist_sweep,
    run_sweep,
    summarize_sweep,
)
from app.services.backtest.types import (
    BacktestConfig,
    PriceField,
    RebalanceFreq,
)
from app.services.backtest.types import (
    BacktestMetrics as Metrics,
)
from sqlalchemy import select, text
from sqlalchemy.orm import Session

PREFIX = "FRA35TEST"


# ---------------------------------------------------------------------------
# 纯单元 helpers + fixtures
# ---------------------------------------------------------------------------


def _prices(n_assets: int = 4, n_days: int = 130, seed: int = 7) -> pd.DataFrame:
    """合成价格宽表:每资产不同漂移的几何随机游走(有动量 / 趋势信号)。

    ``freq='B'`` 取工作日;tz-aware UTC 午夜 index,列名 ``A0..An``。
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-02", periods=n_days, freq="B", tz="UTC")
    drifts = rng.uniform(-0.0003, 0.0008, n_assets)
    rets = rng.normal(0.0, 0.012, (n_days, n_assets)) + drifts
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=idx, columns=[f"A{i}" for i in range(n_assets)])


def _base(strategy_name: str = "ma_crossover", **overrides: object) -> BacktestConfig:
    cols = ("A0", "A1", "A2", "A3")
    kw: dict[str, object] = {
        "universe": cols,
        "start": date(2023, 1, 2),
        "end": date(2023, 7, 14),
        "strategy_name": strategy_name,
        "initial_capital": 100_000.0,
        "cost_bps": 0.0,
        "rebalance": RebalanceFreq.DAILY,
        "price_field": PriceField.ADJUSTED,
    }
    kw.update(overrides)
    return BacktestConfig(**kw)  # type: ignore[arg-type]


def _mk_point(sharpe: float, params: dict[str, int], cost_bps: float = 0.0) -> SweepPoint:
    """人造 SweepPoint(指标全填占位,只让 sharpe / annual_return 有意义)。"""
    m = Metrics(sharpe, 0.1, sharpe, -0.1, 1.0, 1.0, 0.5, 0.0, 0.0)
    return SweepPoint(params=dict(params), cost_bps=cost_bps, gross=m, net=m)


# ---------------------------------------------------------------------------
# 网格展开
# ---------------------------------------------------------------------------


def test_ma_grid_size_and_param_pairs() -> None:
    configs = ma_crossover_configs(_base("ma_crossover"))
    # fast(5,10) × slow(20,50) = 4 策略点 × 4 cost = 16。
    assert len(configs) == 16
    pairs = {(c.strategy_params["fast"], c.strategy_params["slow"]) for c in configs}
    assert pairs == {(5, 20), (5, 50), (10, 20), (10, 50)}
    assert all(c.strategy_params["fast"] < c.strategy_params["slow"] for c in configs)
    assert all(c.cost_bps in DEFAULT_COST_BANDS for c in configs)


def test_ma_grid_filters_fast_ge_slow() -> None:
    # 仅 (5,10) 合法 → 1 策略点 × 4 cost = 4。
    configs = ma_crossover_configs(_base("ma_crossover"), fasts=(5, 10), slows=(5, 10))
    assert len(configs) == 4
    assert {(c.strategy_params["fast"], c.strategy_params["slow"]) for c in configs} == {(5, 10)}


def test_ma_grid_wrong_strategy_raises() -> None:
    with pytest.raises(ValueError, match="ma_crossover"):
        ma_crossover_configs(_base("momentum"))


def test_momentum_grid_includes_rebalance_axis() -> None:
    configs = momentum_configs(_base("momentum"))
    # lookback(21,63) × top_k(1,3) × rebalance(daily,monthly) × 4 cost = 32。
    assert len(configs) == 32
    assert {c.rebalance.value for c in configs} == {"daily", "monthly"}
    assert {c.strategy_params["lookback"] for c in configs} == {21, 63}
    assert {c.strategy_params["top_k"] for c in configs} == {1, 3}


def test_momentum_grid_wrong_strategy_raises() -> None:
    with pytest.raises(ValueError, match="momentum"):
        momentum_configs(_base("ma_crossover"))


# ---------------------------------------------------------------------------
# run_sweep — 成本单调性 + 点/config 对齐
# ---------------------------------------------------------------------------


def test_run_sweep_points_match_configs() -> None:
    prices = _prices()
    configs = ma_crossover_configs(
        _base("ma_crossover"), fasts=(5,), slows=(20,), cost_bands=(0.0, 10.0)
    )
    points = run_sweep(prices, configs)
    assert len(points) == len(configs)
    for p, c in zip(points, configs, strict=True):
        assert p.params == c.strategy_params
        assert p.cost_bps == c.cost_bps
        assert p.net.turnover >= 0.0


def test_run_sweep_cost_bands_degrade_net_and_widen_gap() -> None:
    """固定策略参数只变 cost:gross 不变、net 随成本下降、gross-net gap 随成本扩大。"""
    prices = _prices()
    configs = [
        dataclasses.replace(
            _base("ma_crossover"),
            strategy_params={"fast": 5, "slow": 20},
            cost_bps=cb,
        )
        for cb in (0.0, 5.0, 10.0, 25.0)
    ]
    points = run_sweep(prices, configs)

    grosses = [p.gross.annual_return for p in points]
    nets = [p.net.annual_return for p in points]
    gaps = [p.gross.annual_return - p.net.annual_return for p in points]

    # gross 完全不依赖 cost(成本前口径)→ 4 点几乎相等。
    assert max(grosses) - min(grosses) < 1e-9
    # net = gross − turnover·cost_rate → 随成本单调下降(turnover=0 时相等,断言仍成立)。
    assert nets == sorted(nets, reverse=True)
    # gross-net gap 随成本单调扩大。
    assert gaps == sorted(gaps)


# ---------------------------------------------------------------------------
# summarize_sweep — 指标表 + 高度依赖判定
# ---------------------------------------------------------------------------


def test_summarize_metric_table_and_dimensions() -> None:
    prices = _prices()
    configs = ma_crossover_configs(
        _base("ma_crossover"), fasts=(5,), slows=(20,), cost_bands=(0.0, 10.0)
    )
    points = run_sweep(prices, configs)
    summary = summarize_sweep(points)

    assert len(summary.metric_table) == len(points)
    expected_cols = {
        "params",
        "cost_bps",
        "gross_sharpe",
        "net_sharpe",
        "gross_max_drawdown",
        "net_max_drawdown",
        "turnover",
        "gross_net_return_gap",
    }
    assert expected_cols <= set(summary.metric_table[0])
    # 维度 = 策略参数 key + cost_bps。
    assert {i.param for i in summary.param_impacts} == {"fast", "slow", "cost_bps"}
    sharpes = [p.net.sharpe_ratio for p in points]
    assert summary.best_net_sharpe == pytest.approx(max(sharpes))
    assert summary.worst_net_sharpe == pytest.approx(min(sharpes))


def test_summarize_flags_high_impact_param() -> None:
    # 人造:net sharpe 对 lookback 高度依赖(21→~1.95,63→~0.075)。
    points = [
        _mk_point(2.0, {"lookback": 21, "top_k": 1}),
        _mk_point(1.9, {"lookback": 21, "top_k": 1}),
        _mk_point(0.1, {"lookback": 63, "top_k": 1}),
        _mk_point(0.05, {"lookback": 63, "top_k": 1}),
    ]
    summary = summarize_sweep(points)
    impact = {i.param: i for i in summary.param_impacts}
    assert impact["lookback"].high_impact is True
    assert impact["lookback"].normalized_range > 0.5
    assert summary.highly_sensitive is True


def test_summarize_stable_when_single_param_value() -> None:
    # 每维度只有一个取值 → abs_range=0 → 无高影响维度。
    points = [_mk_point(1.0 + 0.001 * i, {"fast": 5, "slow": 20}, cost_bps=0.0) for i in range(4)]
    summary = summarize_sweep(points)
    assert summary.highly_sensitive is False
    assert all(not i.high_impact for i in summary.param_impacts)


def test_summarize_empty_points() -> None:
    summary = summarize_sweep([])
    assert summary.metric_table == []
    assert summary.highly_sensitive is False
    assert summary.best_net_sharpe is None
    assert summary.worst_net_sharpe is None


# ---------------------------------------------------------------------------
# DB 集成 — persist_sweep
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    runs = "SELECT id FROM backtest_runs WHERE name LIKE :p"
    db.execute(
        text(f"DELETE FROM equity_curve WHERE backtest_run_id IN ({runs})"), {"p": f"{PREFIX}%"}
    )
    db.execute(
        text(f"DELETE FROM backtest_metrics WHERE backtest_run_id IN ({runs})"), {"p": f"{PREFIX}%"}
    )
    db.execute(text("DELETE FROM backtest_runs WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
    db.execute(text("DELETE FROM users WHERE email LIKE :p"), {"p": f"{PREFIX}%"})
    db.commit()


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)
        db.close()


def _make_user(db: Session, suffix: str) -> User:
    user = User(email=f"{PREFIX}-{suffix}@test", hashed_password="x", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_persist_sweep_creates_sensitivity_runs_with_grid(db_session: Session) -> None:
    user = _make_user(db_session, "U1")
    # 内存 prices(sweep 纯计算,不走 load_prices);universe 用占位列名(config_json 非 FK)。
    prices = _prices(n_assets=4, n_days=40, seed=3)
    cols = tuple(prices.columns)
    base = BacktestConfig(
        universe=cols,
        start=date(2023, 1, 2),
        end=date(2023, 3, 1),
        strategy_name="ma_crossover",
        rebalance=RebalanceFreq.DAILY,
        price_field=PriceField.ADJUSTED,
    )
    configs = ma_crossover_configs(base, fasts=(5,), slows=(20,), cost_bands=(0.0, 10.0))
    points = run_sweep(prices, configs)
    grid = {"strategy": "ma_crossover", "fasts": [5], "slows": [20], "cost_bands": [0.0, 10.0]}

    run_ids = persist_sweep(
        db_session,
        user_id=user.id,
        base=base,
        strategy_name="ma_crossover",
        grid=grid,
        points=points,
        name_prefix=PREFIX,
    )

    assert len(run_ids) == 2  # 1 策略点 × 2 cost

    runs = list(
        db_session.scalars(select(BacktestRun).where(BacktestRun.name.like(f"{PREFIX}%"))).all()
    )
    assert len(runs) == 2
    assert all(r.run_kind == "sensitivity" for r in runs)
    assert all(r.status == "success" for r in runs)
    assert all(r.user_id == user.id for r in runs)

    # 每个 run 1:1 metrics(net sharpe 已算)。
    for r in runs:
        m = db_session.get(BacktestMetrics, r.id)
        assert m is not None
        assert m.net_sharpe_ratio is not None

    # config_json 内嵌完整 sweep 网格 + 该点参数(可复现)。
    cfg = runs[0].config_json
    assert cfg["sweep"]["grid"] == grid
    assert cfg["sweep"]["kind"] == "parameter_cost_sensitivity"
    assert cfg["strategy_name"] == "ma_crossover"
    assert "fast" in cfg["strategy_params"] and "slow" in cfg["strategy_params"]
