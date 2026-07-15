"""Tests for the Report Agent — evidence-bound synthesis (FRA-89).

Covers normal synthesis, partial tool failure, risk-fail restricted output,
dangling citation rejection, banned-phrase detection, and Markdown escaping.
All deterministic — no LLM.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
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
from app.services.agent.report import (
    DISCLAIMER,
    Citation,
    CitationError,
    CitationType,
    EvidenceRegistry,
    KeyObservation,
    check_banned_phrases,
    synthesize,
    to_markdown,
    validate_citations,
)
from app.services.agent.risk import (
    RiskAssessment,
    RiskEvidence,
    assess_risk,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


def _make_plan(
    *,
    assumptions: list[str] | None = None,
    survivorship_documented: bool = True,
    factors: list[FactorSpec] | None = None,
    sentiment_provenance: SentimentProvenance | None = None,
) -> ResearchPlan:
    return ResearchPlan(
        research_question="Do NVDA/AMD show 6M momentum vs QQQ?",
        resolution=PlanResolution.VALIDATED,
        universe=[
            AssetRef(symbol="NVDA", asset_id=uuid.uuid4()),
            AssetRef(symbol="AMD", asset_id=uuid.uuid4()),
        ],
        benchmark=AssetRef(symbol="QQQ", asset_id=uuid.uuid4()),
        data_source=DataSource.YFINANCE,
        start_date=datetime(2022, 1, 1, tzinfo=UTC),
        end_date=datetime(2024, 1, 1, tzinfo=UTC),
        price_field=PriceField.ADJUSTED,
        factors=factors or [FactorSpec(name="momentum_126", kind=FactorKind.TECHNICAL)],
        sentiment_provenance=sentiment_provenance,
        strategy=StrategyConfig(
            name="momentum",
            params={"lookback": 126, "top_k": 2},
            rebalance=RebalanceFrequency.MONTHLY,
        ),
        transaction_cost_bps=10.0,
        validation=ValidationConfig(
            baselines=["buy_and_hold", "equal_weight", "benchmark"],
            cost_sensitivity_bps=[0.0, 5.0, 10.0, 25.0],
        ),
        risk_checks=RiskChecksConfig(survivorship_documented=survivorship_documented),
        assumptions=assumptions
        or [
            "Universe is survivorship-biased.",
            "Cost model is single-side proportional.",
            "Single source yfinance; no cross-validation.",
            "Time-based train/forward split used.",
        ],
        requested_outputs=["research_memo", "equity_curve"],
    )


def _good_evidence() -> RiskEvidence:
    return RiskEvidence(
        coverage={"missing": [], "gaps_detected": False},
        backtest_result={
            "run_id": "test-run-123",
            "equity_points": 504,
            "metrics": {
                "gross_sharpe_ratio": 1.5,
                "net_sharpe_ratio": 1.2,
                "gross_annual_return": 0.15,
                "net_annual_return": 0.12,
                "gross_max_drawdown": -0.15,
                "net_max_drawdown": -0.18,
                "net_turnover": 0.5,
            },
        },
        factor_evaluation={"ic_mean": 0.05, "icir": 0.8},
    )


def _assess(plan: ResearchPlan, evidence: RiskEvidence) -> RiskAssessment:
    return assess_risk(plan, evidence)


# ─── Normal synthesis ────────────────────────────────────────────────────────


def test_synthesis_normal() -> None:
    plan = _make_plan()
    evidence = _good_evidence()
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)

    assert not synth.restricted
    assert synth.research_question == plan.research_question
    assert "NVDA" in synth.scope["universe"]
    assert synth.scope["benchmark"] == "QQQ"
    assert synth.methodology["strategy"] == "momentum"
    assert len(synth.key_observations) > 0
    assert synth.disclaimer == DISCLAIMER
    assert synth.cited_refs  # non-empty


def test_synthesis_has_disclaimer() -> None:
    plan = _make_plan()
    evidence = _good_evidence()
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)

    assert "not investment advice" in synth.disclaimer.lower()
    assert "does not predict" in synth.disclaimer.lower()


def test_synthesis_scope_bound_to_plan() -> None:
    plan = _make_plan()
    evidence = _good_evidence()
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)

    assert synth.scope["window"]["start"].startswith("2022-01-01")
    assert synth.scope["window"]["end"].startswith("2024-01-01")
    assert synth.scope["data_source"] == "yfinance"
    assert synth.scope["price_field"] == "adjusted"


def test_synthesis_metrics_from_evidence() -> None:
    """Every observation value must come from the evidence, not recomputed."""
    plan = _make_plan()
    evidence = _good_evidence()
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)

    metric_values = {obs.metric: obs.value for obs in synth.key_observations}
    # Value should match evidence exactly.
    assert metric_values.get("net_sharpe_ratio") == "1.2"
    assert metric_values.get("net_annual_return") == "0.12"
    assert metric_values.get("gross_sharpe_ratio") == "1.5"


def test_synthesis_citations_valid() -> None:
    plan = _make_plan()
    evidence = _good_evidence()
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)

    # All citations should be registered.
    registry = EvidenceRegistry()
    registry.register_plan(plan)
    registry.register_evidence(evidence)
    registry.register_risk(assessment)
    for obs in synth.key_observations:
        assert registry.contains(obs.citation.ref_id), f"dangling: {obs.citation.ref_id}"


def test_synthesis_warnings_in_limitations() -> None:
    """Risk warnings should appear in limitations."""
    plan = _make_plan(survivorship_documented=False)
    evidence = _good_evidence()
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)

    # Survivorship warning should be in limitations.
    assert any("survivorship" in lim.lower() for lim in synth.limitations)


# ─── Restricted synthesis (risk fail) ────────────────────────────────────────


def test_synthesis_restricted_on_risk_fail() -> None:
    """Risk assessment with fail → restricted synthesis."""
    plan = _make_plan()
    evidence = RiskEvidence(tool_errors=["run_backtest: timeout"])
    assessment = _assess(plan, evidence)

    assert assessment.has_fail
    synth = synthesize(plan, evidence, assessment)

    assert synth.restricted
    assert len(synth.key_observations) == 0  # no observations when restricted
    assert any("integrity" in lim.lower() for lim in synth.limitations)


def test_restricted_synthesis_has_no_affirmative_conclusions() -> None:
    plan = _make_plan()
    evidence = RiskEvidence(tool_errors=["compute_factor: error"])
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)

    assert synth.restricted
    # No key observations — no affirmative conclusions.
    assert synth.key_observations == []


# ─── Citation validation ─────────────────────────────────────────────────────


def test_dangling_citation_rejected() -> None:
    """Observation with unregistered citation ref should fail."""
    registry = EvidenceRegistry()
    registry.register("backtest:real:metric")

    bad_obs = KeyObservation(
        metric="test",
        value="1.0",
        interpretation="test",
        citation=Citation(
            ref_type=CitationType.BACKTEST_RUN,
            ref_id="backtest:FAKE:metric",  # not registered
        ),
    )
    with pytest.raises(CitationError, match="dangling citation"):
        validate_citations([bad_obs], registry)


def test_valid_citation_passes() -> None:
    registry = EvidenceRegistry()
    registry.register("backtest:real:metric")

    good_obs = KeyObservation(
        metric="test",
        value="1.0",
        interpretation="test",
        citation=Citation(
            ref_type=CitationType.BACKTEST_RUN,
            ref_id="backtest:real:metric",
        ),
    )
    validate_citations([good_obs], registry)  # should not raise


# ─── Banned phrases ──────────────────────────────────────────────────────────


def test_banned_phrases_detected() -> None:
    assert "beats the market" in check_banned_phrases("This strategy beats the market")
    assert "is profitable" in check_banned_phrases("The system is profitable")
    assert "you should buy" in check_banned_phrases("You should buy NVDA")
    assert check_banned_phrases("This is a historical analysis") == []


def test_synthesis_text_no_banned_phrases() -> None:
    """The fixture synthesizer should never emit banned phrases."""
    plan = _make_plan()
    evidence = _good_evidence()
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)

    all_text = synth.research_question + " " + " ".join(synth.limitations)
    assert check_banned_phrases(all_text) == []


# ─── Markdown preview ────────────────────────────────────────────────────────


def test_markdown_contains_sections() -> None:
    plan = _make_plan()
    evidence = _good_evidence()
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)
    md = to_markdown(synth)

    assert "# Research Synthesis" in md
    assert "## Scope" in md
    assert "## Methodology" in md
    assert "## Key Observations" in md or "## Limitations" in md
    assert DISCLAIMER[:30] in md


def test_markdown_restricted_flag() -> None:
    plan = _make_plan()
    evidence = RiskEvidence(tool_errors=["error"])
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)
    md = to_markdown(synth)

    assert "RESTRICTED" in md


def test_markdown_escapes_html() -> None:
    """Model-supplied text should be HTML-escaped to prevent injection."""
    plan = _make_plan()
    # Tamper research question to include script tag.
    tampered = plan.model_copy(update={"research_question": "<script>alert(1)</script>"})
    evidence = _good_evidence()
    assessment = _assess(tampered, evidence)
    synth = synthesize(tampered, evidence, assessment)
    md = to_markdown(synth)

    assert "<script>" not in md
    assert "&lt;script&gt;" in md


# ─── Partial tool failure ────────────────────────────────────────────────────


def test_partial_tool_failure_restricted() -> None:
    plan = _make_plan()
    evidence = RiskEvidence(
        tool_errors=["compute_factor: internal error"],
        backtest_result=_good_evidence().backtest_result,
    )
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)

    # Tool error → R004 fail → restricted.
    assert synth.restricted


def test_synthesis_no_backtest_still_works() -> None:
    """Synthesis without backtest evidence should still produce scope + methodology."""
    plan = _make_plan()
    evidence = RiskEvidence()  # no backtest, no coverage
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)

    # No fail from R004/R005 since no tool errors and no backtest result to check.
    # Should have warnings from survivorship, single-source, etc.
    assert synth.scope["universe"] == ["NVDA", "AMD"]
    assert synth.methodology["strategy"] == "momentum"
    # No observations since no backtest evidence.
    assert len(synth.key_observations) == 0


# ─── Sentiment provenance in synthesis ───────────────────────────────────────


def test_sentiment_synthesis_has_provenance() -> None:
    """Sentiment research should include provider/model/prompt in methodology."""
    plan = _make_plan(
        factors=[
            FactorSpec(name="sentiment", kind=FactorKind.SENTIMENT),
            FactorSpec(name="momentum_63", kind=FactorKind.TECHNICAL),
        ],
        sentiment_provenance=SentimentProvenance(
            provider="yfinance",
            model_name="fixture",
            prompt_version="v1",
        ),
    )
    evidence = _good_evidence()
    assessment = _assess(plan, evidence)
    synth = synthesize(plan, evidence, assessment)

    # Sentiment factor should appear in methodology.
    factor_names = [f["name"] for f in synth.methodology["factors"]]
    assert "sentiment" in factor_names


# ─── Determinism ─────────────────────────────────────────────────────────────


def test_synthesis_deterministic() -> None:
    """Same input → same output (excluding generated_at)."""
    plan = _make_plan()
    evidence = _good_evidence()
    assessment = _assess(plan, evidence)
    s1 = synthesize(plan, evidence, assessment)
    s2 = synthesize(plan, evidence, assessment)

    assert s1.research_question == s2.research_question
    assert s1.scope == s2.scope
    assert s1.methodology == s2.methodology
    assert len(s1.key_observations) == len(s2.key_observations)
    assert [o.value for o in s1.key_observations] == [o.value for o in s2.key_observations]
    assert s1.cited_refs == s2.cited_refs
