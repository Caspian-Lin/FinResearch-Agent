"""Contract tests for the Week 5 agent schema (FRA-84).

These are the authoritative drift-prevention gate: they (a) validate the shared
canonical fixture through the Pydantic ``ResearchPlan``, (b) cover success /
boundary / illegal samples for every acceptance criterion, (c) assert the state
machine is irreversible at terminal states, and (d) assert the allowlists stay
in sync with the live ``FACTOR_REGISTRY`` / strategy registry so the contract
can never silently drift from the runtime.

The same canonical fixture is also validated by the Zod mirror in
``apps/web/src/agent/research-plan.contract.test.ts`` — frontend and backend
must agree on serialization fields and enum semantics.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from app.schemas.agent import (
    KNOWN_TOOL_NAMES,
    SCHEMA_VERSION,
    STRATEGY_NAMES,
    TECHNICAL_FACTOR_NAMES,
    AgentRunStatus,
    AgentStep,
    AgentStepStatus,
    IllegalStateTransitionError,
    PlanResolution,
    ResearchPlan,
    ToolCall,
    ToolRole,
    assert_run_transition,
    assert_step_transition,
)
from pydantic import ValidationError

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "shared"
    / "src"
    / "__fixtures__"
    / "research-plan.canonical.json"
)


# ─── fixtures / helpers ──────────────────────────────────────────────────────


def valid_plan(**overrides: Any) -> dict[str, Any]:
    """A fully-valid validated plan dict; per-test overrides mutate top-level keys."""
    plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "research_question": "Do AI semis show 6m momentum vs QQQ?",
        "resolution": "validated",
        "universe": [
            {"symbol": "NVDA", "asset_id": "11111111-1111-4111-8111-111111111111"},
        ],
        "benchmark": {"symbol": "QQQ", "asset_id": "66666666-6666-4666-8666-666666666666"},
        "data_source": "yfinance",
        "start_date": "2022-01-01T00:00:00Z",
        "end_date": "2026-06-14T00:00:00Z",
        "price_field": "adjusted",
        "factors": [{"name": "momentum_63", "kind": "technical"}],
        "strategy": {
            "name": "momentum",
            "params": {"lookback": 63, "top_k": 2},
            "rebalance": "monthly",
        },
        "transaction_cost_bps": 10.0,
        "validation": {
            "baselines": ["buy_and_hold", "equal_weight", "benchmark"],
            "metrics": ["annual_return", "sharpe", "max_drawdown", "turnover"],
            "cost_sensitivity_bps": [0.0, 5.0, 10.0, 25.0],
        },
        "assumptions": ["Universe is survivorship-biased."],
        "requested_outputs": ["research_memo"],
    }
    plan.update(overrides)
    return plan


def parse(**overrides: Any) -> ResearchPlan:
    return ResearchPlan.model_validate(valid_plan(**overrides))


def expect_fail(plan: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ResearchPlan.model_validate(plan)


# ─── canonical fixture + success samples ─────────────────────────────────────


def test_canonical_fixture_validates_backend() -> None:
    plan = ResearchPlan.model_validate(json.loads(FIXTURE.read_text()))
    assert plan.schema_version == SCHEMA_VERSION
    assert plan.resolution == PlanResolution.VALIDATED
    assert len(plan.universe) == 5
    assert all(ref.asset_id is not None for ref in plan.universe)
    assert plan.benchmark.asset_id is not None
    assert plan.sentiment_provenance is not None
    assert plan.sentiment_provenance.model_name == "fixture-rule"


def test_minimal_valid_plan_parses() -> None:
    plan = parse()
    assert plan.research_question.startswith("Do AI")
    assert plan.transaction_cost_bps == 10.0


def test_draft_plan_allows_unresolved_assets() -> None:
    p = valid_plan(resolution="draft")
    p["universe"] = [{"symbol": "NVDA"}]  # no asset_id
    p["benchmark"] = {"symbol": "QQQ"}
    plan = ResearchPlan.model_validate(p)
    assert plan.resolution == PlanResolution.DRAFT
    assert plan.universe[0].asset_id is None


def test_zero_transaction_cost_is_allowed() -> None:
    plan = parse(transaction_cost_bps=0.0)
    assert plan.transaction_cost_bps == 0.0


def test_sentiment_factor_with_resolved_provenance_ok() -> None:
    p = valid_plan(
        factors=[{"name": "sentiment", "kind": "sentiment"}],
        sentiment_provenance={
            "provider": "yfinance",
            "model_name": "fixture-rule",
            "prompt_version": "sentiment-v1",
            "pending": False,
        },
    )
    plan = ResearchPlan.model_validate(p)
    assert plan.sentiment_provenance is not None
    assert plan.sentiment_provenance.pending is False


def test_sentiment_provenance_pending_ok_in_draft() -> None:
    p = valid_plan(resolution="draft")
    p["factors"] = [{"name": "sentiment", "kind": "sentiment"}]
    p["benchmark"] = {"symbol": "QQQ"}
    p["universe"] = [{"symbol": "NVDA"}]
    p["sentiment_provenance"] = {"pending": True}
    plan = ResearchPlan.model_validate(p)
    assert plan.sentiment_provenance is not None
    assert plan.sentiment_provenance.pending is True


# ─── boundary / illegal samples (acceptance: schema rejects …) ───────────────


def test_empty_universe_rejected() -> None:
    expect_fail(valid_plan(universe=[]))


def test_inverted_dates_rejected() -> None:
    p = valid_plan(start_date="2027-01-01T00:00:00Z")  # after end_date 2026-06-14
    expect_fail(p)


def test_missing_benchmark_rejected() -> None:
    p = valid_plan()
    p.pop("benchmark")
    expect_fail(p)


def test_missing_transaction_cost_rejected() -> None:
    p = valid_plan()
    p.pop("transaction_cost_bps")
    expect_fail(p)


def test_negative_transaction_cost_rejected() -> None:
    expect_fail(valid_plan(transaction_cost_bps=-1.0))


def test_empty_baselines_rejected() -> None:
    p = valid_plan()
    p["validation"] = {**p["validation"], "baselines": []}
    expect_fail(p)


def test_unknown_baseline_kind_rejected() -> None:
    p = valid_plan()
    p["validation"] = {**p["validation"], "baselines": ["SPY"]}  # raw symbol not allowed
    expect_fail(p)


def test_unknown_technical_factor_rejected() -> None:
    expect_fail(valid_plan(factors=[{"name": "momentum_999", "kind": "technical"}]))


def test_unknown_strategy_rejected() -> None:
    p = valid_plan()
    p["strategy"] = {**p["strategy"], "name": "lstm_reinforce"}
    expect_fail(p)


def test_unknown_tool_rejected() -> None:
    with pytest.raises(ValidationError):
        ToolCall(tool="drop_table", role=ToolRole.DATA)


def test_unknown_agent_role_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentStep(name="x", agent_role="hacker_agent")


def test_unknown_schema_version_rejected() -> None:
    expect_fail(valid_plan(schema_version="0.9"))


def test_unknown_field_rejected() -> None:
    p = valid_plan()
    p["rogue_field"] = "no free-text escape"
    expect_fail(p)


def test_sentiment_factor_without_provenance_rejected() -> None:
    expect_fail(valid_plan(factors=[{"name": "sentiment", "kind": "sentiment"}]))


def test_sentiment_provenance_partial_without_pending_rejected() -> None:
    p = valid_plan(factors=[{"name": "sentiment", "kind": "sentiment"}])
    p["sentiment_provenance"] = {"provider": "yfinance"}  # missing model/prompt, not pending
    expect_fail(p)


def test_sentiment_pending_in_validated_rejected() -> None:
    p = valid_plan(factors=[{"name": "sentiment", "kind": "sentiment"}])
    p["sentiment_provenance"] = {"pending": True}
    expect_fail(p)


def test_sentiment_wrong_name_rejected() -> None:
    p = valid_plan(factors=[{"name": "news_vibe", "kind": "sentiment"}])
    p["sentiment_provenance"] = {
        "provider": "yfinance",
        "model_name": "fixture-rule",
        "prompt_version": "v1",
    }
    expect_fail(p)


def test_validated_plan_with_unresolved_asset_rejected() -> None:
    p = valid_plan()  # resolution = validated
    p["universe"] = [{"symbol": "NVDA"}]  # missing asset_id
    expect_fail(p)


def test_missing_assumptions_rejected() -> None:
    p = valid_plan()
    p.pop("assumptions")
    expect_fail(p)


def test_missing_requested_outputs_rejected() -> None:
    p = valid_plan()
    p.pop("requested_outputs")
    expect_fail(p)


# ─── run state machine ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "current,target",
    [
        (AgentRunStatus.DRAFT, AgentRunStatus.VALIDATED),
        (AgentRunStatus.DRAFT, AgentRunStatus.CANCELED),
        (AgentRunStatus.VALIDATED, AgentRunStatus.QUEUED),
        (AgentRunStatus.VALIDATED, AgentRunStatus.CANCELED),
        (AgentRunStatus.QUEUED, AgentRunStatus.RUNNING),
        (AgentRunStatus.QUEUED, AgentRunStatus.CANCELED),
        (AgentRunStatus.RUNNING, AgentRunStatus.SUCCEEDED),
        (AgentRunStatus.RUNNING, AgentRunStatus.FAILED),
        (AgentRunStatus.RUNNING, AgentRunStatus.CANCELED),
    ],
)
def test_run_allowed_transitions(current: AgentRunStatus, target: AgentRunStatus) -> None:
    assert_run_transition(current, target)  # must not raise


@pytest.mark.parametrize(
    "current,target",
    [
        (AgentRunStatus.DRAFT, AgentRunStatus.RUNNING),  # skip validated
        (AgentRunStatus.VALIDATED, AgentRunStatus.RUNNING),  # skip queued
        (AgentRunStatus.QUEUED, AgentRunStatus.SUCCEEDED),  # skip running
    ],
)
def test_run_illegal_transitions(current: AgentRunStatus, target: AgentRunStatus) -> None:
    with pytest.raises(IllegalStateTransitionError):
        assert_run_transition(current, target)


@pytest.mark.parametrize("current", list(AgentRunStatus))
def test_run_terminal_states_immutable(current: AgentRunStatus) -> None:
    if current in {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED, AgentRunStatus.CANCELED}:
        for target in AgentRunStatus:
            with pytest.raises(IllegalStateTransitionError):
                assert_run_transition(current, target)


# ─── step / tool-call state machine ──────────────────────────────────────────


@pytest.mark.parametrize(
    "current,target",
    [
        (AgentStepStatus.QUEUED, AgentStepStatus.RUNNING),
        (AgentStepStatus.QUEUED, AgentStepStatus.CANCELED),
        (AgentStepStatus.RUNNING, AgentStepStatus.SUCCEEDED),
        (AgentStepStatus.RUNNING, AgentStepStatus.FAILED),
        (AgentStepStatus.RUNNING, AgentStepStatus.CANCELED),
    ],
)
def test_step_allowed_transitions(current: AgentStepStatus, target: AgentStepStatus) -> None:
    assert_step_transition(current, target)


def test_step_terminal_immutable() -> None:
    for current in (AgentStepStatus.SUCCEEDED, AgentStepStatus.FAILED, AgentStepStatus.CANCELED):
        with pytest.raises(IllegalStateTransitionError):
            assert_step_transition(current, AgentStepStatus.RUNNING)


# ─── allowlist sync with the live registries (drift prevention) ──────────────


def test_factor_allowlist_matches_factor_registry() -> None:
    from app.services.factors.service import FACTOR_REGISTRY

    assert set(FACTOR_REGISTRY) == set(TECHNICAL_FACTOR_NAMES)


def test_strategy_allowlist_matches_strategy_registry() -> None:
    from app.services.backtest.strategies.registry import _REGISTRY

    assert set(_REGISTRY) == set(STRATEGY_NAMES)


def test_tool_catalog_is_non_empty_and_covers_all_roles() -> None:
    assert len(KNOWN_TOOL_NAMES) >= 10
    roles = {
        spec.role
        for spec in __import__("app.schemas.agent", fromlist=["TOOL_CATALOG"]).TOOL_CATALOG.values()
    }
    from app.schemas.agent import ToolRole

    assert roles == set(ToolRole)


def test_round_trip_serialization_preserves_fields() -> None:
    plan = parse()
    rt = ResearchPlan.model_validate(plan.model_dump(mode="json"))
    assert rt == plan
    # deepcopy sanity: mutating a cloned plan must not affect the original.
    clone = deepcopy(plan)
    clone.transaction_cost_bps = 0.0
    assert plan.transaction_cost_bps == 10.0
