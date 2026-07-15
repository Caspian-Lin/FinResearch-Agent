"""Tests for the Risk Agent — deterministic research integrity checks (FRA-88).

Covers clean-pass, warnings-only, hard-fail, sentiment, tampered evidence,
and partial-tool-failure scenarios. All tests are deterministic (no LLM).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.schemas.agent import (
    AssetRef,
    DataSource,
    FactorKind,
    FactorSpec,
    PlanResolution,
    PriceField,
    RebalanceFrequency,
    ResearchPlan,
    RiskChecksConfig,
    SentimentProvenance,
    StrategyConfig,
    ValidationConfig,
)
from app.services.agent.risk import (
    FindingStatus,
    RiskEvidence,
    assess_risk,
)

# ─── Plan factory ────────────────────────────────────────────────────────────


def _make_plan(
    *,
    resolution: PlanResolution = PlanResolution.VALIDATED,
    universe: list[AssetRef] | None = None,
    benchmark: AssetRef | None = None,
    factors: list[FactorSpec] | None = None,
    sentiment_provenance: SentimentProvenance | None = None,
    survivorship_documented: bool = False,
    assumptions: list[str] | None = None,
    cost_sensitivity_bps: list[float] | None = None,
) -> ResearchPlan:
    """Build a minimal valid ResearchPlan for testing."""
    if cost_sensitivity_bps is None:
        cost_sensitivity_bps = [0.0, 5.0, 10.0, 25.0]
    _asset = uuid.uuid4()
    return ResearchPlan(
        research_question="Test hypothesis?",
        resolution=resolution,
        universe=universe or [AssetRef(symbol="NVDA", asset_id=_asset)],
        benchmark=benchmark or AssetRef(symbol="QQQ", asset_id=uuid.uuid4()),
        data_source=DataSource.YFINANCE,
        start_date=datetime(2022, 1, 1, tzinfo=UTC),
        end_date=datetime(2024, 1, 1, tzinfo=UTC),
        price_field=PriceField.ADJUSTED,
        factors=factors or [],
        sentiment_provenance=sentiment_provenance,
        strategy=StrategyConfig(
            name="momentum",
            params={"lookback": 126},
            rebalance=RebalanceFrequency.MONTHLY,
        ),
        transaction_cost_bps=10.0,
        validation=ValidationConfig(
            baselines=["buy_and_hold", "equal_weight", "benchmark"],
            cost_sensitivity_bps=list(cost_sensitivity_bps) if cost_sensitivity_bps else [],
        ),
        risk_checks=RiskChecksConfig(survivorship_documented=survivorship_documented),
        assumptions=assumptions
        or [
            "Universe is survivorship-biased.",
            "Cost model is single-side proportional.",
        ],
        requested_outputs=["research_memo", "equity_curve"],
    )


# ─── Clean pass ──────────────────────────────────────────────────────────────


def test_clean_pass_no_evidence() -> None:
    """Plan with all mandatory fields, no tool evidence → pass with warnings."""
    plan = _make_plan(survivorship_documented=True)
    evidence = RiskEvidence()
    assessment = assess_risk(plan, evidence)

    assert assessment.overall_status == FindingStatus.WARN  # warnings from single-source etc.
    assert not assessment.has_fail


def test_clean_pass_with_full_evidence() -> None:
    """Plan + full evidence + documented assumptions → minimal warnings."""
    plan = _make_plan(
        survivorship_documented=True,
        assumptions=[
            "Universe is survivorship-biased.",
            "Cost model is single-side proportional.",
            "Single source yfinance; no cross-validation.",
            "Time-based train/forward split used.",
        ],
    )
    evidence = RiskEvidence(
        coverage={"missing": [], "gaps_detected": False},
        backtest_result={
            "run_id": "test-run",
            "equity_points": 504,
            "metrics": {
                "gross_sharpe_ratio": 1.2,
                "net_sharpe_ratio": 1.0,
                "gross_max_drawdown": -0.15,
                "net_max_drawdown": -0.18,
                "gross_annual_return": 0.12,
                "net_annual_return": 0.10,
                "net_turnover": 0.5,
            },
        },
    )
    assessment = assess_risk(plan, evidence)

    assert assessment.overall_status == FindingStatus.PASS
    assert len(assessment.findings) == 0


# ─── Hard fails ──────────────────────────────────────────────────────────────


def test_fail_missing_benchmark() -> None:
    """Defense-in-depth: R001 catches a benchmark that lost its asset_id
    after validation (e.g. via a buggy tool). Uses model_copy to bypass
    the schema validator."""
    plan = _make_plan()  # valid
    tampered = plan.model_copy(update={"benchmark": AssetRef(symbol="QQQ")})
    assessment = assess_risk(tampered, RiskEvidence())

    assert assessment.has_fail
    assert "R001_benchmark_exists" in assessment.failed_rules


def test_fail_missing_cost_sensitivity() -> None:
    """Defense-in-depth: R002 catches empty cost sensitivity after validation."""
    plan = _make_plan()
    tampered = plan.validation.model_copy(update={"cost_sensitivity_bps": []})
    tampered_plan = plan.model_copy(update={"validation": tampered})
    assessment = assess_risk(tampered_plan, RiskEvidence())

    assert assessment.has_fail
    assert "R002_cost_sensitivity" in assessment.failed_rules


def test_fail_tool_errors() -> None:
    plan = _make_plan(survivorship_documented=True)
    evidence = RiskEvidence(tool_errors=["compute_factor: internal error"])
    assessment = assess_risk(plan, evidence)

    assert assessment.has_fail
    assert "R004_evidence_complete" in assessment.failed_rules


def test_fail_missing_gross_net_metrics() -> None:
    plan = _make_plan(survivorship_documented=True)
    evidence = RiskEvidence(backtest_result={"run_id": "r1", "equity_points": 504, "metrics": None})
    assessment = assess_risk(plan, evidence)

    assert assessment.has_fail
    assert "R005_gross_net_metrics" in assessment.failed_rules


def test_fail_partial_metrics() -> None:
    plan = _make_plan(survivorship_documented=True)
    evidence = RiskEvidence(
        backtest_result={
            "run_id": "r1",
            "equity_points": 504,
            "metrics": {"net_sharpe_ratio": 1.0},  # no gross
        }
    )
    assessment = assess_risk(plan, evidence)

    assert assessment.has_fail
    assert "R005_gross_net_metrics" in assessment.failed_rules


def test_fail_sentiment_pending() -> None:
    """Defense-in-depth: R009 catches pending sentiment provenance after
    validation (simulates a tool that cleared the provenance)."""
    plan = _make_plan(
        factors=[FactorSpec(name="sentiment", kind=FactorKind.SENTIMENT)],
        sentiment_provenance=SentimentProvenance(
            provider="yfinance", model_name="fixture", prompt_version="v1"
        ),
    )
    tampered = plan.model_copy(update={"sentiment_provenance": SentimentProvenance(pending=True)})
    assessment = assess_risk(tampered, RiskEvidence())

    assert assessment.has_fail
    assert "R009_sentiment_provenance" in assessment.failed_rules


# ─── Warnings ────────────────────────────────────────────────────────────────


def test_warn_survivorship() -> None:
    plan = _make_plan(survivorship_documented=False)
    assessment = assess_risk(plan, RiskEvidence())

    rules = [f.rule_id for f in assessment.warnings]
    assert "R006_survivorship" in rules


def test_warn_short_window() -> None:
    plan = _make_plan(survivorship_documented=True)
    evidence = RiskEvidence(
        backtest_result={
            "run_id": "r1",
            "equity_points": 100,
            "metrics": {
                "gross_sharpe_ratio": 1.0,
                "net_sharpe_ratio": 0.8,
                "gross_max_drawdown": -0.1,
                "net_max_drawdown": -0.12,
            },
        }
    )
    assessment = assess_risk(plan, evidence)

    rules = [f.rule_id for f in assessment.warnings]
    assert "R007_sample_length" in rules


def test_warn_data_gaps() -> None:
    plan = _make_plan(survivorship_documented=True)
    evidence = RiskEvidence(coverage={"missing": ["asset-1", "asset-2"], "gaps_detected": True})
    assessment = assess_risk(plan, evidence)

    rules = [f.rule_id for f in assessment.warnings]
    assert "R008_data_coverage" in rules


def test_warn_max_drawdown_extreme() -> None:
    plan = _make_plan(survivorship_documented=True)
    evidence = RiskEvidence(
        backtest_result={
            "run_id": "r1",
            "equity_points": 504,
            "metrics": {
                "gross_sharpe_ratio": 1.0,
                "net_sharpe_ratio": 0.5,
                "gross_max_drawdown": -0.45,
                "net_max_drawdown": -0.50,
            },
        }
    )
    assessment = assess_risk(plan, evidence)

    rules = [f.rule_id for f in assessment.warnings]
    assert "R010_max_drawdown" in rules


def test_warn_single_source() -> None:
    plan = _make_plan(
        survivorship_documented=True,
        assumptions=["Some assumption without mentioning source."],
    )
    assessment = assess_risk(plan, RiskEvidence())

    rules = [f.rule_id for f in assessment.warnings]
    assert "R011_single_source" in rules


# ─── Determinism ─────────────────────────────────────────────────────────────


def test_assessment_is_deterministic() -> None:
    """Same input → same findings (excluding assessed_at timestamp)."""
    plan = _make_plan(survivorship_documented=True)
    evidence = RiskEvidence()
    a1 = assess_risk(plan, evidence)
    a2 = assess_risk(plan, evidence)

    assert [f.rule_id for f in a1.findings] == [f.rule_id for f in a2.findings]
    assert [f.status for f in a1.findings] == [f.status for f in a2.findings]
    assert a1.plan_hash == a2.plan_hash


def test_plan_hash_differs_for_different_plans() -> None:
    p1 = _make_plan(survivorship_documented=True)
    p2 = _make_plan(survivorship_documented=False)
    a1 = assess_risk(p1, RiskEvidence())
    a2 = assess_risk(p2, RiskEvidence())

    assert a1.plan_hash != a2.plan_hash


# ─── Evidence binding ────────────────────────────────────────────────────────


def test_finding_has_evidence_ref() -> None:
    """Failed tool finding must reference the evidence."""
    plan = _make_plan(survivorship_documented=True)
    evidence = RiskEvidence(
        tool_errors=["run_backtest: timeout"],
        backtest_result={
            "run_id": "rb-123",
            "equity_points": 504,
            "metrics": {
                "gross_sharpe_ratio": 1.0,
                "net_sharpe_ratio": 0.8,
                "gross_max_drawdown": -0.1,
                "net_max_drawdown": -0.12,
            },
        },
    )
    assessment = assess_risk(plan, evidence)

    fail_findings = [f for f in assessment.findings if f.status == FindingStatus.FAIL]
    assert fail_findings
    for f in fail_findings:
        assert f.evidence_ref is not None or f.plan_field is not None


def test_restricted_report_gate() -> None:
    """When assessment has fail, report must be restricted."""
    plan = _make_plan()
    tampered = plan.validation.model_copy(update={"cost_sensitivity_bps": []})
    tampered_plan = plan.model_copy(update={"validation": tampered})
    assessment = assess_risk(tampered_plan, RiskEvidence())

    assert assessment.has_fail
    # The Report Agent should check `assessment.has_fail` to decide
    # whether to produce a restricted synthesis.
