"""Factor parameter/cost sensitivity sweep tests (FRA-54).

纯单元(无 DB)覆盖:因子网格展开(factor × window × top_k/quantile × rebalance ×
cost)、非法组合过滤、``run_sweep`` 因子/成本维度生效、``FactorStrategy`` 选股
正确性、``summarize_sweep`` 维度。DB 集成覆盖 ``persist_sweep`` 入库
(``run_kind='factor_sensitivity'`` + 1:1 metrics + config_json 含因子参数 + 网格)。
"""

from __future__ import annotations

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
    DEFAULT_FACTOR_WINDOWS,
    factor_sensitivity_configs,
    persist_sweep,
    run_sweep,
    summarize_sweep,
)
from app.services.backtest.strategies.factor import FactorStrategy
from app.services.backtest.strategies.registry import get_strategy
from app.services.backtest.types import (
    BacktestConfig,
    PriceField,
    RebalanceFreq,
)
from app.services.factors.momentum import momentum
from sqlalchemy import select, text
from sqlalchemy.orm import Session

PREFIX = "FRA54TEST"


# ---------------------------------------------------------------------------
# helpers + fixtures
# ---------------------------------------------------------------------------


def _prices(n_assets: int = 5, n_days: int = 140, seed: int = 7) -> pd.DataFrame:
    """合成价格宽表:每资产不同漂移的几何随机游走(有动量 / 趋势信号)。"""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-02", periods=n_days, freq="B", tz="UTC")
    drifts = rng.uniform(-0.0003, 0.0008, n_assets)
    rets = rng.normal(0.0, 0.012, (n_days, n_assets)) + drifts
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=idx, columns=[f"A{i}" for i in range(n_assets)])


def _base(**overrides: object) -> BacktestConfig:
    kw: dict[str, object] = {
        "universe": ("A0", "A1", "A2", "A3", "A4"),
        "start": date(2023, 1, 2),
        "end": date(2023, 8, 1),
        "strategy_name": "factor",
        "initial_capital": 100_000.0,
        "cost_bps": 0.0,
        "rebalance": RebalanceFreq.DAILY,
        "price_field": PriceField.ADJUSTED,
    }
    kw.update(overrides)
    return BacktestConfig(**kw)  # type: ignore[arg-type]


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


# ---------------------------------------------------------------------------
# 1) factor_sensitivity_configs — 网格展开 + 非法过滤
# ---------------------------------------------------------------------------


def test_factor_grid_size_and_structure_default() -> None:
    configs = factor_sensitivity_configs(_base())
    # momentum 3×2×3×4=72, rsi 2×2×3×4=48, volatility 2×2×3×4=48 → 168。
    assert len(configs) == 168
    assert all(c.strategy_name == "factor" for c in configs)
    assert {c.rebalance.value for c in configs} == {"daily", "weekly", "monthly"}
    assert all(c.cost_bps in DEFAULT_COST_BANDS for c in configs)
    # 每点 params 必含 factor / window / top_k(top_k 模式默认)。
    assert all({"factor", "window", "top_k"} <= set(c.strategy_params) for c in configs)
    assert {c.strategy_params["factor"] for c in configs} == {"momentum", "rsi", "volatility"}


def test_factor_grid_window_counts_match_default_map() -> None:
    configs = factor_sensitivity_configs(_base())
    # 每个因子出现的窗口档与 DEFAULT_FACTOR_WINDOWS 一致。
    for fac, windows in DEFAULT_FACTOR_WINDOWS.items():
        got = {c.strategy_params["window"] for c in configs if c.strategy_params["factor"] == fac}
        assert got == set(windows)


def test_factor_grid_filters_nonpositive_window() -> None:
    configs = factor_sensitivity_configs(
        _base(),
        factors=("momentum",),
        windows={"momentum": (-1, 0, 21)},
        top_ks=(1,),
        rebalances=("daily",),
        cost_bands=(0.0,),
    )
    # 仅 window=21 合法 → 1 点。
    assert len(configs) == 1
    assert configs[0].strategy_params["window"] == 21


def test_factor_grid_filters_nonpositive_top_k() -> None:
    configs = factor_sensitivity_configs(
        _base(),
        factors=("rsi",),
        windows={"rsi": (14,)},
        top_ks=(0, -2, 3),
        rebalances=("daily",),
        cost_bands=(0.0,),
    )
    # 仅 top_k=3 合法 → 1 点。
    assert len(configs) == 1
    assert configs[0].strategy_params["top_k"] == 3


def test_factor_grid_filters_invalid_quantile() -> None:
    configs = factor_sensitivity_configs(
        _base(),
        factors=("volatility",),
        windows={"volatility": (20,)},
        top_ks=(),
        quantiles=(0, 3, 5, 99),
        n_quantiles=5,
        rebalances=("daily",),
        cost_bands=(0.0,),
    )
    # 仅 quantile=3 与 quantile=5 合法 → 2 点。
    assert len(configs) == 2
    qs = sorted(c.strategy_params["quantile"] for c in configs)
    assert qs == [3, 5]
    assert all(c.strategy_params["n_quantiles"] == 5 for c in configs)
    # quantile 模式点不含 top_k。
    assert all("top_k" not in c.strategy_params for c in configs)


def test_factor_grid_skips_factor_without_windows() -> None:
    configs = factor_sensitivity_configs(
        _base(),
        factors=("momentum", "rsi"),
        windows={"rsi": (7, 14)},  # momentum 无窗口档 → 跳过
        top_ks=(1,),
        rebalances=("daily",),
        cost_bands=(0.0,),
    )
    # 仅 rsi 展开:2 窗口 × 1 top_k × 1 rb × 1 cost = 2 点,全 rsi。
    assert len(configs) == 2
    assert all(c.strategy_params["factor"] == "rsi" for c in configs)


def test_factor_grid_wrong_strategy_raises() -> None:
    with pytest.raises(ValueError, match="factor"):
        factor_sensitivity_configs(_base(strategy_name="momentum"))


# ---------------------------------------------------------------------------
# 2) run_sweep — 因子维度 + 成本维度生效(复用 sweep 框架)
# ---------------------------------------------------------------------------


def test_run_sweep_factor_dimension_changes_metrics() -> None:
    prices = _prices(n_assets=5, n_days=140, seed=11)
    configs = factor_sensitivity_configs(
        _base(),
        factors=("momentum",),
        windows={"momentum": (21, 63)},
        top_ks=(1,),
        rebalances=("daily",),
        cost_bands=(0.0,),
    )
    points = run_sweep(prices, configs)
    assert len(points) == 2
    # 不同 window → 不同 net Sharpe(因子维度生效)。
    sharpes = {p.params["window"]: p.net.sharpe_ratio for p in points}
    assert sharpes[21] != sharpes[63]


def test_run_sweep_cost_dimension_drags_net_sharpe() -> None:
    prices = _prices(n_assets=5, n_days=140, seed=11)
    configs = factor_sensitivity_configs(
        _base(),
        factors=("momentum",),
        windows={"momentum": (63,)},
        top_ks=(1,),
        rebalances=("daily",),
        cost_bands=(0.0, 25.0),
    )
    points = run_sweep(prices, configs)
    by_cost = {p.cost_bps: p.net.sharpe_ratio for p in points}
    # 成本越高 net Sharpe 越低(或相等,若几乎无换手)。
    assert by_cost[25.0] <= by_cost[0.0] + 1e-9


# ---------------------------------------------------------------------------
# 3) FactorStrategy — 选股正确性(单元)
# ---------------------------------------------------------------------------


def test_factor_strategy_momentum_top_k_one_picks_strongest() -> None:
    prices = _prices(n_assets=5, n_days=80, seed=3)
    strat = FactorStrategy("momentum", window=21, top_k=1)
    weights = strat.weights(prices)
    # 窗口足够的最后一行:top_k=1 → 最强动量资产权重 1.0,其余 0。
    mom = momentum(prices, 21).iloc[-1]
    strongest = str(mom.idxmax())
    last_row = weights.iloc[-1]
    assert last_row[strongest] == pytest.approx(1.0)
    assert last_row.drop(strongest).sum() == pytest.approx(0.0)
    # 每行权重和 ∈ {0, 1}(空选日 0 / 满选日 1)。用手动容差,避免 pytest.approx
    # 对 pandas Series 返回标量而非逐元素比较。
    row_sums = weights.sum(axis=1)
    assert ((row_sums < 1e-9) | (row_sums > 1.0 - 1e-9)).all()


def test_factor_strategy_warmup_rows_all_cash() -> None:
    prices = _prices(n_assets=4, n_days=40, seed=5)
    strat = FactorStrategy("momentum", window=21, top_k=1)
    weights = strat.weights(prices)
    # 前 21 行动量窗口不足 → 全现金(权重和 0)。
    assert (weights.iloc[:21].sum(axis=1) == 0.0).all()
    # 第 22 行起有非现金行(窗口足够)。
    assert (weights.iloc[21:].sum(axis=1) > 0.0).any()


def test_factor_strategy_quantile_mode_selects_layer() -> None:
    prices = _prices(n_assets=10, n_days=80, seed=9)
    strat = FactorStrategy("momentum", window=21, quantile=5, n_quantiles=5)
    weights = strat.weights(prices)
    # 最后一行:选中资产数 = 最高 quintile 层(10 资产 5 层 → 2 资产)。
    last = weights.iloc[-1]
    selected = last[last > 0]
    assert len(selected) == 2
    # 等权。
    assert selected.std() == pytest.approx(0.0)


def test_factor_strategy_rejects_invalid_params() -> None:
    with pytest.raises(ValueError):
        FactorStrategy("unknown", window=21)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        FactorStrategy("momentum", window=0)
    with pytest.raises(ValueError):
        FactorStrategy("momentum", window=21, top_k=0)
    with pytest.raises(ValueError):
        FactorStrategy("momentum", window=21, quantile=6, n_quantiles=5)


def test_factor_strategy_resolvable_via_registry() -> None:
    prices = _prices(n_assets=4, n_days=60, seed=2)
    strat = get_strategy("factor", {"factor": "rsi", "window": 14, "top_k": 3})
    assert isinstance(strat, FactorStrategy)
    weights = strat.weights(prices)
    assert weights.shape == prices.shape


# ---------------------------------------------------------------------------
# 4) summarize_sweep — 维度含因子参数 + cost
# ---------------------------------------------------------------------------


def test_summarize_factor_sweep_dimensions() -> None:
    prices = _prices(n_assets=5, n_days=140, seed=11)
    configs = factor_sensitivity_configs(
        _base(),
        factors=("momentum", "rsi"),
        windows={"momentum": (21, 63), "rsi": (14,)},
        top_ks=(1, 3),
        rebalances=("daily",),
        cost_bands=(0.0, 10.0),
    )
    points = run_sweep(prices, configs)
    summary = summarize_sweep(points)
    dims = {i.param for i in summary.param_impacts}
    # 策略参数维度 + cost_bps。
    assert {"factor", "window", "top_k", "cost_bps"} <= dims
    assert summary.best_net_sharpe is not None and summary.worst_net_sharpe is not None
    assert summary.best_net_sharpe >= summary.worst_net_sharpe


# ---------------------------------------------------------------------------
# 5) DB 集成 — persist_sweep(factor_sensitivity run_kind)
# ---------------------------------------------------------------------------


def test_persist_factor_sweep_creates_factor_sensitivity_runs(db_session: Session) -> None:
    user = _make_user(db_session, "U1")
    prices = _prices(n_assets=4, n_days=80, seed=3)
    cols = tuple(prices.columns)
    base = BacktestConfig(
        universe=cols,
        start=date(2023, 1, 2),
        end=date(2023, 5, 1),
        strategy_name="factor",
        rebalance=RebalanceFreq.DAILY,
        price_field=PriceField.ADJUSTED,
    )
    configs = factor_sensitivity_configs(
        base,
        factors=("momentum",),
        windows={"momentum": (21,)},
        top_ks=(1,),
        rebalances=("daily",),
        cost_bands=(0.0, 10.0),
    )
    points = run_sweep(prices, configs)
    grid = {
        "factors": ["momentum"],
        "windows": {"momentum": [21]},
        "top_ks": [1],
        "rebalances": ["daily"],
        "cost_bands": [0.0, 10.0],
    }

    run_ids = persist_sweep(
        db_session,
        user_id=user.id,
        base=base,
        strategy_name="factor",
        grid=grid,
        points=points,
        name_prefix=PREFIX,
    )

    assert len(run_ids) == 2  # 1 策略点 × 2 cost

    runs = list(
        db_session.scalars(select(BacktestRun).where(BacktestRun.name.like(f"{PREFIX}%"))).all()
    )
    assert len(runs) == 2
    # 关键:factor sweep → run_kind='factor_sensitivity'(String(32) 容纳)。
    assert all(r.run_kind == "factor_sensitivity" for r in runs)
    assert all(r.user_id == user.id for r in runs)

    # 每个 run 1:1 metrics。
    for r in runs:
        m = db_session.get(BacktestMetrics, r.id)
        assert m is not None
        assert m.net_sharpe_ratio is not None

    # config_json 内嵌因子参数 + 完整网格(可复现)。
    cfg = runs[0].config_json
    assert cfg["strategy_name"] == "factor"
    assert cfg["sweep"]["grid"] == grid
    sp = cfg["strategy_params"]
    assert sp["factor"] == "momentum" and sp["window"] == 21 and sp["top_k"] == 1


def test_persist_factor_sweep_explicit_run_kind_validated(db_session: Session) -> None:
    user = _make_user(db_session, "U2")
    prices = _prices(n_assets=3, n_days=60, seed=4)
    base = BacktestConfig(
        universe=tuple(prices.columns),
        start=date(2023, 1, 2),
        end=date(2023, 4, 1),
        strategy_name="factor",
        rebalance=RebalanceFreq.DAILY,
        price_field=PriceField.ADJUSTED,
    )
    configs = factor_sensitivity_configs(
        base,
        factors=("rsi",),
        windows={"rsi": (14,)},
        top_ks=(1,),
        rebalances=("daily",),
        cost_bands=(0.0,),
    )
    points = run_sweep(prices, configs)
    # 显式非法 run_kind → 拒绝。
    with pytest.raises(ValueError, match="run_kind"):
        persist_sweep(
            db_session,
            user_id=user.id,
            base=base,
            strategy_name="factor",
            grid={},
            points=points,
            name_prefix=PREFIX,
            run_kind="bogus",
        )
