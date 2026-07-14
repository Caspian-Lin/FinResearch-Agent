"""Tests for the Research Planner Agent (FRA-86).

Covers:
* FixturePlanner: bilingual parsing, clarification paths, unsupported strategy,
  asset resolution, provenance.
* LLMPlanner: success, bounded repair, max-repairs-exhausted, clarification,
  HTTP retry (429→200), provenance, no-API-key guard.
* DbAssetResolver: found, ambiguous, not-found.
* Registry: get_planner default / explicit / unknown.
* No test touches the public network — LLM calls use a fake httpx.Client.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.schemas.agent import PlanResolution
from app.services.agent.planner import (
    PROMPT_VERSION,
    SUPPORTED_PLANNERS,
    DbAssetResolver,
    FixtureAssetResolver,
    FixturePlanner,
    LLMPlanner,
    _should_retry,
    get_planner,
)
from sqlalchemy import text
from sqlalchemy.orm import Session
from tenacity import Retrying, retry_if_exception, stop_after_attempt

PREFIX = "FRA86TEST"


# ─── DB helpers ──────────────────────────────────────────────────────────────


def _cleanup(db: Session) -> None:
    db.execute(
        text("DELETE FROM assets WHERE symbol LIKE :p OR name LIKE :p"),
        {"p": f"{PREFIX}%"},
    )
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


def _make_asset(
    db: Session,
    symbol: str,
    *,
    exchange: str = "NASDAQ",
    data_source: str = "yfinance",
) -> Asset:
    asset = Asset(
        symbol=symbol,
        name=f"{symbol} Inc.",
        exchange=exchange,
        asset_type="stock",
        data_source=data_source,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


# ─── Fake httpx helpers (LLM tests) ──────────────────────────────────────────


class _FakeResp:
    """Stand-in for httpx.Response."""

    def __init__(
        self,
        data: Any,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._data = data
        self.status_code = status_code
        self.headers = headers or {}
        self.request = httpx.Request("POST", "http://fake/chat/completions")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=httpx.Response(self.status_code),
            )

    def json(self) -> Any:
        return self._data


class _FakeClient:
    """Stand-in for httpx.Client; returns queued responses."""

    def __init__(self, responses: list[_FakeResp]) -> None:
        self._responses = list(responses)
        self.posts: list[dict[str, Any]] = []

    def post(self, url: str, *, json: Any = None, headers: Any = None) -> _FakeResp:
        self.posts.append({"url": url, "json": json, "headers": headers})
        if not self._responses:
            raise AssertionError("no more fake responses queued")
        return self._responses.pop(0)


def _llm(
    fake: _FakeClient,
    *,
    max_repairs: int = 2,
    retryer: Retrying | None = None,
) -> LLMPlanner:
    """Build an LLMPlanner with a fake httpx client (centralized cast for mypy)."""
    return LLMPlanner(
        client=cast(httpx.Client, fake),
        api_key="fake",
        max_repairs=max_repairs,
        retryer=retryer,
    )


def _llm_response(content: str, *, id_: str = "chatcmpl-fake") -> _FakeResp:
    return _FakeResp(
        {
            "id": id_,
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
        }
    )


def _valid_plan_json() -> str:
    return json.dumps(
        {
            "research_question": "Do NVDA/AMD show 6M momentum vs QQQ?",
            "universe": [{"symbol": "NVDA"}, {"symbol": "AMD"}],
            "benchmark": {"symbol": "QQQ"},
            "data_source": "yfinance",
            "start_date": "2022-01-01T00:00:00Z",
            "end_date": "2025-12-31T00:00:00Z",
            "price_field": "adjusted",
            "factors": [{"name": "momentum_126", "kind": "technical", "params": {}}],
            "strategy": {
                "name": "momentum",
                "params": {"lookback": 126, "top_k": 2},
                "rebalance": "monthly",
            },
            "transaction_cost_bps": 10.0,
            "validation": {
                "baselines": ["buy_and_hold", "equal_weight", "benchmark"],
                "metrics": ["annual_return", "sharpe", "max_drawdown", "turnover"],
                "cost_sensitivity_bps": [0.0, 5.0, 10.0, 25.0],
            },
            "assumptions": [
                "Survivorship-biased (current constituents only).",
                "Cost model: single-side proportional in bps.",
            ],
            "requested_outputs": ["research_memo", "equity_curve"],
        }
    )


# ─── FixturePlanner: canonical cases ─────────────────────────────────────────


def test_fixture_canonical_chinese() -> None:
    """比较 NVDA/AMD 6M momentum 与 QQQ,2022-2025，月度调仓."""
    planner = FixturePlanner()
    result = planner.plan("比较 NVDA/AMD 6M momentum 与 QQQ，2022-2025，月度调仓")

    assert result.ok
    assert result.plan is not None
    plan = result.plan

    assert plan.resolution == PlanResolution.DRAFT
    assert [r.symbol for r in plan.universe] == ["NVDA", "AMD"]
    assert plan.benchmark.symbol == "QQQ"
    assert plan.data_source.value == "yfinance"
    assert plan.start_date == datetime(2022, 1, 1, tzinfo=UTC)
    assert plan.end_date == datetime(2025, 12, 31, tzinfo=UTC)
    assert plan.price_field.value == "adjusted"
    assert any(f.name == "momentum_126" for f in plan.factors)
    assert plan.strategy.name == "momentum"
    assert plan.strategy.rebalance.value == "monthly"
    assert plan.transaction_cost_bps == 10.0
    assert "buy_and_hold" in plan.validation.baselines
    assert "benchmark" in plan.validation.baselines
    assert plan.validation.cost_sensitivity_bps == [0.0, 5.0, 10.0, 25.0]
    assert len(plan.assumptions) >= 1
    assert len(plan.requested_outputs) >= 1


def test_fixture_canonical_english() -> None:
    """Compare NVDA/AMD 6M momentum vs QQQ, 2022-2025, monthly rebalance."""
    planner = FixturePlanner()
    result = planner.plan("Compare NVDA/AMD 6M momentum vs QQQ, 2022-2025, monthly rebalance")

    assert result.ok
    plan = result.plan
    assert plan is not None
    assert [r.symbol for r in plan.universe] == ["NVDA", "AMD"]
    assert plan.benchmark.symbol == "QQQ"
    assert plan.strategy.name == "momentum"
    assert plan.strategy.rebalance.value == "monthly"


def test_fixture_provenance() -> None:
    planner = FixturePlanner()
    result = planner.plan("NVDA/AMD momentum vs QQQ, 2022-2025, monthly")
    assert result.provenance is not None
    assert result.provenance.provider == "fixture"
    assert result.provenance.model == "fixture-rule"
    assert result.provenance.prompt_version == PROMPT_VERSION
    assert result.provenance.request_id is None
    assert result.provenance.token_usage is None
    assert result.provenance.repair_attempts == 0
    assert result.provenance.elapsed_ms >= 0


# ─── FixturePlanner: clarification / rejection ───────────────────────────────


def test_fixture_missing_window() -> None:
    planner = FixturePlanner()
    result = planner.plan("NVDA/AMD momentum vs QQQ, monthly rebalance")
    assert result.plan is None
    assert result.clarification_needed is not None
    assert "time range" in result.clarification_needed.lower()


def test_fixture_missing_benchmark() -> None:
    planner = FixturePlanner()
    result = planner.plan("NVDA/AMD momentum, 2022-2025, monthly")
    assert result.plan is None
    assert result.clarification_needed is not None
    assert "benchmark" in result.clarification_needed.lower()


def test_fixture_missing_universe() -> None:
    planner = FixturePlanner()
    result = planner.plan("momentum vs QQQ, 2022-2025, monthly")
    assert result.plan is None
    assert result.clarification_needed is not None
    assert "universe" in result.clarification_needed.lower()


def test_fixture_unsupported_strategy() -> None:
    planner = FixturePlanner()
    result = planner.plan("Use machine learning to predict NVDA prices, 2022-2025, monthly")
    assert result.plan is None
    assert result.clarification_needed is not None
    assert "not supported" in result.clarification_needed.lower()


# ─── FixturePlanner: asset resolution ────────────────────────────────────────


def test_fixture_with_resolver_validated() -> None:
    nvda_id = uuid.uuid4()
    amd_id = uuid.uuid4()
    qqq_id = uuid.uuid4()
    resolver = FixtureAssetResolver({"NVDA": nvda_id, "AMD": amd_id, "QQQ": qqq_id})
    planner = FixturePlanner()
    result = planner.plan(
        "NVDA/AMD 6M momentum vs QQQ, 2022-2025, monthly",
        resolver=resolver,
    )
    assert result.ok
    assert result.plan is not None
    assert result.plan.resolution == PlanResolution.VALIDATED
    assert result.plan.universe[0].asset_id == nvda_id
    assert result.plan.benchmark.asset_id == qqq_id


def test_fixture_with_resolver_unknown_asset() -> None:
    nvda_id = uuid.uuid4()
    resolver = FixtureAssetResolver({"NVDA": nvda_id})  # AMD + QQQ missing
    planner = FixturePlanner()
    result = planner.plan(
        "NVDA/AMD 6M momentum vs QQQ, 2022-2025, monthly",
        resolver=resolver,
    )
    # Plan is still produced as draft but with validation errors.
    assert result.validation_errors
    assert any("AMD" in e for e in result.validation_errors)
    assert any("QQQ" in e for e in result.validation_errors)


def test_fixture_sentiment_factor_pending_provenance() -> None:
    planner = FixturePlanner()
    result = planner.plan("NVDA/AMD sentiment vs QQQ, 2022-2025, monthly rebalance")
    assert result.ok
    assert result.plan is not None
    assert any(f.kind.value == "sentiment" for f in result.plan.factors)
    assert result.plan.sentiment_provenance is not None
    assert result.plan.sentiment_provenance.pending is True


# ─── LLMPlanner: success ─────────────────────────────────────────────────────


def test_llm_success_first_try() -> None:
    fake = _FakeClient([_llm_response(_valid_plan_json())])
    planner = _llm(fake, max_repairs=2)
    result = planner.plan("Test hypothesis")

    assert result.ok
    assert result.plan is not None
    assert result.plan.research_question.startswith("Do NVDA/AMD")
    assert result.provenance is not None
    assert result.provenance.provider == "openai"
    assert result.provenance.request_id == "chatcmpl-fake"
    assert result.provenance.token_usage is not None
    assert result.provenance.token_usage.total_tokens == 700
    assert result.provenance.repair_attempts == 0


def test_llm_clarification_response() -> None:
    fake = _FakeClient([_llm_response(json.dumps({"clarification_needed": "Which benchmark?"}))])
    planner = _llm(fake, max_repairs=2)
    result = planner.plan("vague hypothesis")

    assert result.plan is None
    assert result.clarification_needed == "Which benchmark?"


# ─── LLMPlanner: bounded repair ──────────────────────────────────────────────


def test_llm_repair_succeeds_on_second_attempt() -> None:
    bad_plan = json.loads(_valid_plan_json())
    del bad_plan["transaction_cost_bps"]  # missing mandatory field

    fake = _FakeClient(
        [
            _llm_response(json.dumps(bad_plan)),
            _llm_response(_valid_plan_json()),
        ]
    )
    planner = _llm(fake, max_repairs=2)
    result = planner.plan("Test hypothesis")

    assert result.ok
    assert result.plan is not None
    assert result.provenance is not None
    assert result.provenance.repair_attempts == 1
    assert len(fake.posts) == 2  # two API calls


def test_llm_max_repairs_exhausted() -> None:
    bad_plan = json.loads(_valid_plan_json())
    del bad_plan["transaction_cost_bps"]

    responses = [_llm_response(json.dumps(bad_plan)) for _ in range(3)]
    fake = _FakeClient(responses)
    planner = _llm(fake, max_repairs=2)
    result = planner.plan("Test hypothesis")

    assert not result.ok
    assert result.plan is None
    assert result.validation_errors
    assert result.provenance is not None
    assert result.provenance.repair_attempts == 2
    assert len(fake.posts) == 3  # 1 original + 2 repairs


def test_llm_invalid_json_repair() -> None:
    fake = _FakeClient(
        [
            _llm_response("this is not json at all"),
            _llm_response(_valid_plan_json()),
        ]
    )
    planner = _llm(fake, max_repairs=2)
    result = planner.plan("Test hypothesis")

    assert result.ok
    assert result.provenance is not None
    assert result.provenance.repair_attempts == 1


# ─── LLMPlanner: HTTP retry ──────────────────────────────────────────────────


def test_llm_http_429_then_success() -> None:
    fake = _FakeClient(
        [
            _FakeResp({"error": "rate limited"}, status_code=429),
            _llm_response(_valid_plan_json()),
        ]
    )
    retryer = Retrying(
        retry=retry_if_exception(_should_retry),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    planner = _llm(fake, max_repairs=0, retryer=retryer)
    result = planner.plan("Test hypothesis")

    assert result.ok
    assert result.plan is not None
    assert len(fake.posts) == 2  # retried after 429


def test_llm_http_500_all_fail() -> None:
    fake = _FakeClient(
        [
            _FakeResp({"error": "server"}, status_code=500),
            _FakeResp({"error": "server"}, status_code=500),
            _FakeResp({"error": "server"}, status_code=500),
        ]
    )
    retryer = Retrying(
        retry=retry_if_exception(_should_retry),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    planner = _llm(fake, max_repairs=0, retryer=retryer)
    result = planner.plan("Test hypothesis")

    assert not result.ok
    assert result.plan is None
    assert result.validation_errors
    assert "LLM request failed" in result.validation_errors[0]


# ─── LLMPlanner: no API key ──────────────────────────────────────────────────


def test_llm_no_api_key_raises() -> None:
    planner = LLMPlanner(api_key="", max_repairs=0)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        planner.plan("test")


# ─── LLMPlanner: with resolver ───────────────────────────────────────────────


def test_llm_with_resolver_validated() -> None:
    nvda_id = uuid.uuid4()
    amd_id = uuid.uuid4()
    qqq_id = uuid.uuid4()
    resolver = FixtureAssetResolver({"NVDA": nvda_id, "AMD": amd_id, "QQQ": qqq_id})
    fake = _FakeClient([_llm_response(_valid_plan_json())])
    planner = _llm(fake, max_repairs=0)
    result = planner.plan("Test hypothesis", resolver=resolver)

    assert result.ok
    assert result.plan is not None
    assert result.plan.resolution == PlanResolution.VALIDATED
    assert result.plan.universe[0].asset_id == nvda_id
    assert result.plan.benchmark.asset_id == qqq_id


# ─── LLMPlanner: no code/sql/shell in output ─────────────────────────────────


def test_llm_rejects_plan_with_code_injection() -> None:
    """LLM tries to inject code via strategy params — Pydantic extra=forbid at
    ResearchPlan level blocks unknown top-level fields. Strategy params is
    dict[str, Any] (the constructor accepts arbitrary kwargs for templated
    strategies), so code inside params is inert at planning time — the real
    protection is that strategies are loaded from a registry, never eval'd
    (FRA-87). This test verifies the top-level extra=forbid barrier.
    """
    malicious = json.loads(_valid_plan_json())
    malicious["execute_code"] = "import os; os.system('rm -rf /')"
    fake = _FakeClient(
        [
            _llm_response(json.dumps(malicious)),
            _llm_response(json.dumps(malicious)),
            _llm_response(json.dumps(malicious)),
        ]
    )
    planner = _llm(fake, max_repairs=2)
    result = planner.plan("test")

    assert not result.ok
    assert result.validation_errors


def test_llm_rejects_extra_top_level_fields() -> None:
    """ResearchPlan has extra='forbid' — unknown top-level fields are rejected."""
    plan_with_extra = json.loads(_valid_plan_json())
    plan_with_extra["evil_field"] = "rm -rf /"
    fake = _FakeClient(
        [
            _llm_response(json.dumps(plan_with_extra)),
            _llm_response(json.dumps(plan_with_extra)),
            _llm_response(json.dumps(plan_with_extra)),
        ]
    )
    planner = _llm(fake, max_repairs=2)
    result = planner.plan("test")

    assert not result.ok
    assert result.validation_errors


# ─── DbAssetResolver ─────────────────────────────────────────────────────────


def test_db_resolver_found(db_session: Session) -> None:
    asset = _make_asset(db_session, f"{PREFIX}-AAPL")
    resolver = DbAssetResolver(db_session)
    res = resolver.resolve(f"{PREFIX}-AAPL")
    assert res.found
    assert not res.ambiguous
    assert res.asset_id == asset.id


def test_db_resolver_not_found(db_session: Session) -> None:
    resolver = DbAssetResolver(db_session)
    res = resolver.resolve(f"{PREFIX}-NONEXIST")
    assert not res.found
    assert res.asset_id is None


def test_db_resolver_ambiguous(db_session: Session) -> None:
    sym = f"{PREFIX}-DUAL"
    _make_asset(db_session, sym, exchange="NASDAQ")
    _make_asset(db_session, sym, exchange="NYSE")
    resolver = DbAssetResolver(db_session)
    res = resolver.resolve(sym)
    assert res.found
    assert res.ambiguous
    assert set(res.exchanges) == {"NASDAQ", "NYSE"}


def test_db_resolver_data_source(db_session: Session) -> None:
    _make_asset(db_session, f"{PREFIX}-ASHARE", exchange="SSE", data_source="akshare")
    resolver = DbAssetResolver(db_session)
    res = resolver.resolve(f"{PREFIX}-ASHARE")
    assert res.found
    assert res.data_source == "akshare"


# ─── Registry ────────────────────────────────────────────────────────────────


def test_get_planner_default_is_fixture() -> None:
    planner = get_planner()
    assert isinstance(planner, FixturePlanner)


def test_get_planner_explicit_fixture() -> None:
    planner = get_planner("fixture")
    assert isinstance(planner, FixturePlanner)


def test_get_planner_explicit_openai() -> None:
    planner = get_planner("openai")
    assert isinstance(planner, LLMPlanner)


def test_get_planner_unknown_key() -> None:
    with pytest.raises(ValueError, match="unsupported planner"):
        get_planner("nonsense")


def test_supported_planners() -> None:
    assert "fixture" in SUPPORTED_PLANNERS
    assert "openai" in SUPPORTED_PLANNERS


# ─── End-to-end: fixture planner → validated plan ────────────────────────────


def test_e2e_fixture_to_validated_with_db(db_session: Session) -> None:
    """Fixture planner produces a plan, DB resolver validates it."""
    # Use real ticker symbols (so the planner can extract them) with test-
    # prefixed names (so _cleanup removes them after the test).
    nvda = Asset(symbol="NVDA", name=f"{PREFIX} NVIDIA", exchange="NASDAQ", asset_type="stock")
    amd = Asset(symbol="AMD", name=f"{PREFIX} AMD", exchange="NASDAQ", asset_type="stock")
    qqq = Asset(symbol="QQQ", name=f"{PREFIX} QQQ", exchange="NASDAQ", asset_type="etf")
    db_session.add_all([nvda, amd, qqq])
    db_session.commit()
    db_session.refresh(nvda)
    db_session.refresh(amd)
    db_session.refresh(qqq)

    resolver = DbAssetResolver(db_session)
    planner = FixturePlanner()
    result = planner.plan(
        "NVDA/AMD momentum vs QQQ, 2022-2025, monthly",
        resolver=resolver,
    )

    assert result.ok
    assert result.plan is not None
    assert result.plan.resolution == PlanResolution.VALIDATED
    assert result.plan.universe[0].asset_id == nvda.id
    assert result.plan.universe[1].asset_id == amd.id
    assert result.plan.benchmark.asset_id == qqq.id
