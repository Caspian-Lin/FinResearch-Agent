"""Tests for SentimentTechStrategy + comparison runner (FRA-71).

Pure-unit tests (no DB) for strategy selection logic, overlay filtering, combined
ranking, param validation, anti-look-ahead, anti-double-lag, and protocol
conformance. Comparison runner tests verify both strategies run under identical
conditions.

API tests (with DB) verify POST /backtest/comparison + GET /backtest/comparison/{id}.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.asset import Asset
from app.models.backtest import BacktestMetrics, BacktestRun, EquityCurvePoint
from app.services.backtest.comparison import ComparisonResult, run_comparison
from app.services.backtest.engine import run_backtest
from app.services.backtest.protocols import Strategy
from app.services.backtest.strategies.sentiment_tech import SentimentTechStrategy
from app.services.backtest.types import BacktestConfig, RebalanceFreq
from app.services.sync import get_backtest_queue
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

ASSET_A = "11111111-1111-1111-1111-111111111111"
ASSET_B = "22222222-2222-2222-2222-222222222222"
ASSET_C = "33333333-3333-3333-3333-333333333333"
ASSETS = [ASSET_A, ASSET_B, ASSET_C]


def _ts(day: str) -> pd.Timestamp:
    return pd.Timestamp(datetime.fromisoformat(f"{day}T00:00:00"), tz="UTC")


def _prices(day_prices: dict[str, list[float]], asset_ids: list[str]) -> pd.DataFrame:
    days = sorted(day_prices)
    index = pd.DatetimeIndex([_ts(d) for d in days])
    data = {aid: [day_prices[d][i] for d in days] for i, aid in enumerate(asset_ids)}
    return pd.DataFrame(data, index=index, columns=asset_ids).astype("float64")


# 3-asset deterministic trend: A up (high momentum), B flat, C down (low momentum).
TREND: dict[str, list[float]] = {
    "2024-01-02": [10.0, 10.0, 10.0],
    "2024-01-03": [11.0, 10.0, 9.0],
    "2024-01-04": [12.0, 10.0, 8.0],
    "2024-01-05": [13.0, 10.0, 7.0],
}


def _trend_prices() -> pd.DataFrame:
    return _prices(TREND, ASSETS)


def _sentiment_frame() -> pd.DataFrame:
    """Sentiment: A bullish (+0.5), B bearish (-0.3), C neutral (0.0).

    All rows identical (no time variation) to isolate the filter effect.
    """
    idx = pd.DatetimeIndex([_ts(d) for d in sorted(TREND)])
    return pd.DataFrame(
        {
            ASSET_A: [0.5, 0.5, 0.5, 0.5],
            ASSET_B: [-0.3, -0.3, -0.3, -0.3],
            ASSET_C: [0.0, 0.0, 0.0, 0.0],
        },
        index=idx,
        columns=ASSETS,
    ).astype("float64")


def _config(**overrides: Any) -> BacktestConfig:
    fields: dict[str, Any] = {
        "universe": tuple(ASSETS),
        "start": date(2024, 1, 2),
        "end": date(2024, 1, 5),
        "strategy_name": "sentiment_tech",
        "initial_capital": 100_000.0,
        "cost_bps": 0.0,
        "rebalance": RebalanceFreq.DAILY,
    }
    fields.update(overrides)
    return BacktestConfig(**fields)


# ===========================================================================
# 1) Pure-technical mode (sentiment_frame=None)
# ===========================================================================


def test_pure_technical_matches_factor_strategy_selection() -> None:
    """Without sentiment_frame, strategy selects by technical factor only."""
    strat = SentimentTechStrategy(technical_factor="momentum", window=2, top_k=1)
    target = strat.weights(_trend_prices())
    # After warmup (2 rows), A has highest momentum → all weight on A.
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        assert target.loc[ts, ASSET_A] == pytest.approx(1.0)
        assert target.loc[ts, ASSET_B] == pytest.approx(0.0)
        assert target.loc[ts, ASSET_C] == pytest.approx(0.0)


def test_pure_technical_warmup_is_cash() -> None:
    """Window=2 → first 2 rows have NaN momentum → all cash."""
    strat = SentimentTechStrategy(technical_factor="momentum", window=2, top_k=1)
    target = strat.weights(_trend_prices())
    assert target.iloc[0].sum() == pytest.approx(0.0)
    assert target.iloc[1].sum() == pytest.approx(0.0)


# ===========================================================================
# 2) Overlay mode: technical selects, sentiment filters
# ===========================================================================


def test_overlay_filters_bearish_sentiment() -> None:
    """top_k=2 selects A,B; sentiment_threshold=0.0 filters B (bearish).

    A has sentiment +0.5 (pass), B has -0.3 (fail), C has 0.0 (pass but not
    selected by technical). Result: only A survives → weight 1.0 on A.
    """
    strat = SentimentTechStrategy(
        technical_factor="momentum",
        window=2,
        top_k=2,
        mode="overlay",
        sentiment_threshold=0.0,
        sentiment_frame=_sentiment_frame(),
    )
    target = strat.weights(_trend_prices())
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        assert target.loc[ts, ASSET_A] == pytest.approx(1.0)
        assert target.loc[ts, ASSET_B] == pytest.approx(0.0)


def test_overlay_all_filtered_is_cash() -> None:
    """If all selected assets fail the sentiment threshold → all cash."""
    # threshold=0.6: A(+0.5) also fails → no survivors.
    strat = SentimentTechStrategy(
        technical_factor="momentum",
        window=2,
        top_k=3,
        mode="overlay",
        sentiment_threshold=0.6,
        sentiment_frame=_sentiment_frame(),
    )
    target = strat.weights(_trend_prices())
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        assert target.loc[ts].sum() == pytest.approx(0.0)


def test_overlay_nan_sentiment_filtered() -> None:
    """NaN sentiment → asset excluded (no forward-fill of stale signal)."""
    sent = _sentiment_frame()
    sent.loc[:, ASSET_A] = np.nan  # A has no news coverage
    strat = SentimentTechStrategy(
        technical_factor="momentum",
        window=2,
        top_k=3,
        mode="overlay",
        sentiment_threshold=-1.0,  # accept everything except NaN
        sentiment_frame=sent,
    )
    target = strat.weights(_trend_prices())
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        # A excluded (NaN sentiment); B and C survive → equal weight.
        assert target.loc[ts, ASSET_A] == pytest.approx(0.0)
        assert target.loc[ts, ASSET_B] == pytest.approx(0.5)
        assert target.loc[ts, ASSET_C] == pytest.approx(0.5)


# ===========================================================================
# 3) Combined mode: weighted rank-average
# ===========================================================================


def test_combined_rank_selects_top() -> None:
    """Combined mode: A has highest rank in both → selected with top_k=1."""
    strat = SentimentTechStrategy(
        technical_factor="momentum",
        window=2,
        top_k=1,
        mode="combined",
        sentiment_weight=0.5,
        sentiment_frame=_sentiment_frame(),
    )
    target = strat.weights(_trend_prices())
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        # A is top in both momentum and sentiment → selected.
        assert target.loc[ts, ASSET_A] == pytest.approx(1.0)


def test_combined_weight_extremes() -> None:
    """sentiment_weight=0 → pure technical; sentiment_weight=1 → pure sentiment."""
    prices = _trend_prices()
    sent = _sentiment_frame()

    # weight=0: equivalent to pure technical ranking.
    s0 = SentimentTechStrategy(
        technical_factor="momentum",
        window=2,
        top_k=1,
        mode="combined",
        sentiment_weight=0.0,
        sentiment_frame=sent,
    )
    # weight=1: equivalent to pure sentiment ranking.
    s1 = SentimentTechStrategy(
        technical_factor="momentum",
        window=2,
        top_k=1,
        mode="combined",
        sentiment_weight=1.0,
        sentiment_frame=sent,
    )
    w0 = s0.weights(prices)
    w1 = s1.weights(prices)

    # After warmup: pure tech selects A (highest momentum).
    for ts in [_ts("2024-01-04"), _ts("2024-01-05")]:
        assert w0.loc[ts, ASSET_A] == pytest.approx(1.0)
        # Pure sentiment: A (+0.5) is also highest → also selects A.
        assert w1.loc[ts, ASSET_A] == pytest.approx(1.0)


# ===========================================================================
# 4) Parameter validation
# ===========================================================================


def test_invalid_technical_factor() -> None:
    with pytest.raises(ValueError, match="technical_factor"):
        SentimentTechStrategy(technical_factor="invalid")  # type: ignore[arg-type]


def test_invalid_window() -> None:
    with pytest.raises(ValueError, match="window"):
        SentimentTechStrategy(window=0)


def test_invalid_top_k() -> None:
    with pytest.raises(ValueError, match="top_k"):
        SentimentTechStrategy(top_k=0)


def test_invalid_mode() -> None:
    with pytest.raises(ValueError, match="mode"):
        SentimentTechStrategy(mode="invalid")  # type: ignore[arg-type]


def test_invalid_sentiment_threshold() -> None:
    with pytest.raises(ValueError, match="sentiment_threshold"):
        SentimentTechStrategy(sentiment_threshold=2.0)


def test_invalid_sentiment_weight() -> None:
    with pytest.raises(ValueError, match="sentiment_weight"):
        SentimentTechStrategy(sentiment_weight=-0.1)


# ===========================================================================
# 5) Anti-look-ahead + anti-double-lag
# ===========================================================================


def test_future_price_does_not_move_past_signals() -> None:
    """Changing the last price row doesn't affect weights on earlier rows."""
    prices = _trend_prices()
    sent = _sentiment_frame()

    prices_var = _prices(
        {
            "2024-01-02": [10.0, 10.0, 10.0],
            "2024-01-03": [11.0, 10.0, 9.0],
            "2024-01-04": [12.0, 10.0, 8.0],
            "2024-01-05": [13.0, 10.0, 70.0],  # C spikes on last day
        },
        ASSETS,
    )

    strat = SentimentTechStrategy(
        technical_factor="momentum",
        window=2,
        top_k=1,
        mode="overlay",
        sentiment_threshold=0.0,
        sentiment_frame=sent,
    )
    w_base = strat.weights(prices)
    w_var = strat.weights(prices_var)

    # Rows ≤ 01-04 must be identical (future change doesn't leak backwards).
    pd.testing.assert_frame_equal(w_base.iloc[:3], w_var.iloc[:3])


def test_future_sentiment_does_not_move_past_signals() -> None:
    """Changing future sentiment doesn't affect past weights."""
    prices = _trend_prices()
    sent = _sentiment_frame()

    sent_var = sent.copy()
    sent_var.loc[_ts("2024-01-05"), ASSET_A] = -0.9  # A turns bearish on last day

    strat = SentimentTechStrategy(
        technical_factor="momentum",
        window=2,
        top_k=2,
        mode="overlay",
        sentiment_threshold=0.0,
        sentiment_frame=sent,
    )
    w_base = strat.weights(prices)

    strat_var = SentimentTechStrategy(
        technical_factor="momentum",
        window=2,
        top_k=2,
        mode="overlay",
        sentiment_threshold=0.0,
        sentiment_frame=sent_var,
    )
    w_var = strat_var.weights(prices)

    # Rows ≤ 01-04 must be identical.
    pd.testing.assert_frame_equal(w_base.iloc[:3], w_var.iloc[:3])
    # On 01-05: A's sentiment is -0.9 → filtered out.
    assert w_var.loc[_ts("2024-01-05"), ASSET_A] == pytest.approx(0.0)


def test_signal_at_t_moves_holding_at_t_plus_one() -> None:
    """Engine shift(1): signal at t → holding at t+1, not t."""
    res = run_backtest(
        _trend_prices(),
        SentimentTechStrategy(
            technical_factor="momentum",
            window=2,
            top_k=1,
            sentiment_frame=_sentiment_frame(),
        ),
        _config(),
    )
    holdings = res.positions
    t2 = _ts("2024-01-04")  # signal appears
    t3 = _ts("2024-01-05")  # signal takes effect
    assert holdings.loc[t2, ASSET_A] == pytest.approx(0.0)
    assert holdings.loc[t3, ASSET_A] == pytest.approx(1.0)


# ===========================================================================
# 6) Protocol + shape + end-to-end
# ===========================================================================


def test_satisfies_strategy_protocol() -> None:
    strat = SentimentTechStrategy(sentiment_frame=_sentiment_frame())
    assert isinstance(strat, Strategy)


def test_shape_matches_prices() -> None:
    prices = _trend_prices()
    strat = SentimentTechStrategy(sentiment_frame=_sentiment_frame())
    target = strat.weights(prices)
    assert target.shape == prices.shape
    assert list(target.index) == list(prices.index)
    assert list(target.columns) == list(prices.columns)


def test_row_sums_in_unit_interval() -> None:
    strat = SentimentTechStrategy(
        technical_factor="momentum",
        window=2,
        top_k=2,
        mode="overlay",
        sentiment_threshold=0.0,
        sentiment_frame=_sentiment_frame(),
    )
    target = strat.weights(_trend_prices())
    row_sums = target.sum(axis=1)
    assert (row_sums >= -1e-9).all()
    assert (row_sums <= 1.0 + 1e-9).all()


def test_end_to_end_engine_produces_result() -> None:
    res = run_backtest(
        _trend_prices(),
        SentimentTechStrategy(
            technical_factor="momentum",
            window=2,
            top_k=1,
            sentiment_frame=_sentiment_frame(),
        ),
        _config(),
    )
    assert res.equity_curve.iloc[0] == 100_000.0
    assert res.daily_returns.iloc[0] == 0.0
    assert res.metrics is None


# ===========================================================================
# 7) Comparison runner
# ===========================================================================


def test_comparison_runs_both_strategies() -> None:
    """Comparison produces technical + sentiment_tech results under same config."""
    prices = _trend_prices()
    sent = _sentiment_frame()
    config = _config()

    result = run_comparison(
        prices,
        sent,
        config,
        strategy_params={
            "technical_factor": "momentum",
            "window": 2,
            "top_k": 1,
            "mode": "overlay",
            "sentiment_threshold": 0.0,
        },
    )

    assert isinstance(result, ComparisonResult)
    assert result.technical is not None
    assert result.sentiment_tech is not None
    assert result.sentiment_only is None  # not requested

    # Both share the same equity curve length (same prices/config).
    assert len(result.technical.equity_curve) == len(result.sentiment_tech.equity_curve)
    assert len(result.technical.equity_curve) == len(prices)


def test_comparison_with_sentiment_only() -> None:
    """include_sentiment_only=True adds a third result."""
    result = run_comparison(
        _trend_prices(),
        _sentiment_frame(),
        _config(),
        strategy_params={
            "technical_factor": "momentum",
            "window": 2,
            "top_k": 1,
            "include_sentiment_only": True,
        },
    )
    assert result.sentiment_only is not None


def test_comparison_empty_prices_raises() -> None:
    with pytest.raises(ValueError, match="prices"):
        run_comparison(
            pd.DataFrame(),
            _sentiment_frame(),
            _config(),
            strategy_params={},
        )


def test_comparison_empty_sentiment_raises() -> None:
    with pytest.raises(ValueError, match="sentiment_frame"):
        run_comparison(
            _trend_prices(),
            pd.DataFrame(),
            _config(),
            strategy_params={},
        )


def test_comparison_overlay_changes_holdings_vs_technical() -> None:
    """Technical-only holds B (top_k=2); overlay filters B → different holdings."""
    prices = _trend_prices()
    sent = _sentiment_frame()

    result = run_comparison(
        prices,
        sent,
        _config(),
        strategy_params={
            "technical_factor": "momentum",
            "window": 2,
            "top_k": 2,
            "mode": "overlay",
            "sentiment_threshold": 0.0,
        },
    )

    # On 01-05 (post-warmup):
    # Technical-only: selects A+B (top_k=2 momentum) → holds A+B.
    # Overlay: B sentiment=-0.3 < 0.0 → filtered → only A.
    ts = _ts("2024-01-05")
    tech_holdings = result.technical.positions
    sent_holdings = result.sentiment_tech.positions
    # The signal appears at t=01-04, holding at t+1=01-05.
    assert tech_holdings.loc[ts, ASSET_B] > 0  # B held in technical
    assert sent_holdings.loc[ts, ASSET_B] == pytest.approx(0.0)  # B filtered in overlay


# ===========================================================================
# 8) API tests (DB-backed)
# ===========================================================================

PREFIX = "FRA71TEST"


def _cleanup(db: Session) -> None:
    runs = "SELECT id FROM backtest_runs WHERE name LIKE :p"
    db.execute(
        text(f"DELETE FROM equity_curve WHERE backtest_run_id IN ({runs})"),
        {"p": f"{PREFIX}%"},
    )
    db.execute(
        text(f"DELETE FROM backtest_metrics WHERE backtest_run_id IN ({runs})"),
        {"p": f"{PREFIX}%"},
    )
    db.execute(
        text(f"DELETE FROM trades WHERE backtest_run_id IN ({runs})"),
        {"p": f"{PREFIX}%"},
    )
    db.execute(text("DELETE FROM backtest_runs WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
    db.execute(text("DELETE FROM assets WHERE symbol LIKE :p"), {"p": f"{PREFIX}%"})
    db.execute(text("DELETE FROM users WHERE email ILIKE :p"), {"p": f"{PREFIX}%"})
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


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_backtest_queue] = lambda: MagicMock()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _register(client: TestClient, suffix: str) -> tuple[str, uuid.UUID]:
    email = f"{PREFIX}-{suffix}@example.com"
    reg = client.post("/auth/register", json={"email": email, "password": "supersecretpw"})
    assert reg.status_code == 201, reg.text
    r = client.post("/auth/login", json={"email": email, "password": "supersecretpw"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"], uuid.UUID(reg.json()["id"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_asset(db: Session, symbol: str) -> Asset:
    asset = Asset(
        symbol=symbol,
        name=f"Test {symbol}",
        exchange="NASDAQ",
        asset_type="stock",
        currency="USD",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _comparison_payload(name: str, asset_ids: list[uuid.UUID], **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "universe": [str(a) for a in asset_ids],
        "start": "2024-01-02",
        "end": "2024-01-31",
        "model_name": "gpt-4o-mini",
        "strategy_params": {
            "technical_factor": "momentum",
            "window": 21,
            "top_k": 2,
            "mode": "overlay",
            "sentiment_threshold": 0.0,
        },
    }
    payload.update(overrides)
    return payload


def test_create_comparison_enqueues_run(client: TestClient, db_session: Session) -> None:
    token, _ = _register(client, "U1")
    asset = _make_asset(db_session, f"{PREFIX}-A")

    r = client.post(
        "/backtest/comparison",
        json=_comparison_payload(f"{PREFIX}-run1", [asset.id]),
        headers=_auth(token),
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"
    run_id = uuid.UUID(body["run_id"])

    run = db_session.get(BacktestRun, run_id)
    assert run is not None
    assert run.run_kind == "sentiment_comparison"
    assert run.status == "pending"
    assert run.config_json["model_name"] == "gpt-4o-mini"


def test_create_comparison_unknown_asset_404(client: TestClient, db_session: Session) -> None:
    token, _ = _register(client, "U2")
    r = client.post(
        "/backtest/comparison",
        json=_comparison_payload(f"{PREFIX}-run2", [uuid.uuid4()]),
        headers=_auth(token),
    )
    assert r.status_code == 404


def test_create_comparison_start_after_end_422(client: TestClient, db_session: Session) -> None:
    token, _ = _register(client, "U3")
    asset = _make_asset(db_session, f"{PREFIX}-B")
    r = client.post(
        "/backtest/comparison",
        json=_comparison_payload(
            f"{PREFIX}-run3", [asset.id], start="2024-03-01", end="2024-01-01"
        ),
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_get_comparison_not_found(client: TestClient, db_session: Session) -> None:
    token, _ = _register(client, "U4")
    r = client.get(
        f"/backtest/comparison/{uuid.uuid4()}",
        headers=_auth(token),
    )
    assert r.status_code == 404


def test_get_comparison_returns_children(client: TestClient, db_session: Session) -> None:
    """GET /backtest/comparison/{id} returns parent + child runs."""
    token, user_id = _register(client, "U5")
    asset = _make_asset(db_session, f"{PREFIX}-C")

    # Create a parent run with result_json pointing to child runs.
    parent = BacktestRun(
        user_id=user_id,
        name=f"{PREFIX}-parent",
        strategy_type="sentiment_comparison",
        config_json={
            "universe": [str(asset.id)],
            "model_name": "gpt-4o-mini",
            "strategy_params": {},
        },
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 31),
        price_field="adjusted",
        status="success",
        run_kind="sentiment_comparison",
        result_json={"child_runs": [], "groups": []},
    )
    db_session.add(parent)
    db_session.commit()
    db_session.refresh(parent)

    # Create child runs.
    child_ids: list[str] = []
    for role, label in [("technical", "Technical-only"), ("sentiment_tech", "Tech+Sentiment")]:
        child = BacktestRun(
            user_id=user_id,
            name=f"{PREFIX}-child-{role}",
            strategy_type=f"sentiment_comparison_{role}",
            config_json={
                "comparison_role": role,
                "comparison_label": label,
                "comparison_parent": str(parent.id),
            },
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 31),
            price_field="adjusted",
            status="success",
            run_kind="backtest",
        )
        db_session.add(child)
        db_session.flush()
        db_session.add(
            BacktestMetrics(
                backtest_run_id=child.id,
                gross_annual_return=Decimal("0.15"),
                net_annual_return=Decimal("0.13"),
            )
        )
        db_session.add(
            EquityCurvePoint(
                backtest_run_id=child.id,
                series_kind="strategy",
                time=datetime(2024, 1, 2, tzinfo=UTC),
                equity=Decimal("100000"),
            )
        )
        child_ids.append(str(child.id))

    parent.result_json = {"child_runs": child_ids, "groups": ["technical", "sentiment_tech"]}
    db_session.commit()

    r = client.get(
        f"/backtest/comparison/{parent.id}",
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["run"]["run_kind"] == "sentiment_comparison"
    assert len(body["children"]) == 2
    roles = {c["role"] for c in body["children"]}
    assert roles == {"technical", "sentiment_tech"}
    # Each child has metrics.
    for child in body["children"]:
        assert child["metrics"] is not None
        assert child["metrics"]["net_annual_return"] == 0.13


def test_get_comparison_other_user_404(client: TestClient, db_session: Session) -> None:
    """A comparison run owned by another user returns 404."""
    token1, _ = _register(client, "USER_A")
    token2, _ = _register(client, "USER_B")

    asset = _make_asset(db_session, f"{PREFIX}-D")

    # User A creates the comparison.
    r = client.post(
        "/backtest/comparison",
        json=_comparison_payload(f"{PREFIX}-runA", [asset.id]),
        headers=_auth(token1),
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]

    # User B tries to read it → 404.
    r2 = client.get(
        f"/backtest/comparison/{run_id}",
        headers=_auth(token2),
    )
    assert r2.status_code == 404
