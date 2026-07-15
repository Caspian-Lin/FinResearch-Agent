"""Report Agent — evidence-bound research synthesis (FRA-89).

Produces a structured ``ResearchSynthesis`` from a validated ``ResearchPlan``,
tool evidence, and a ``RiskAssessment``. Every number, window, and asset in the
synthesis must carry a citation traceable to a plan field, tool result, or
risk finding — the LLM (when used) may only organize controlled evidence; it
may never compute or fabricate metrics.

When the RiskAssessment has any ``fail`` finding, the output is a **restricted
synthesis** that explicitly states the research did not pass integrity checks
and produces no affirmative performance conclusion.

Safety: the synthesis always includes a non-investment-advice disclaimer and
avoids promotional language ("beats the market", "profitable", "buy", "sell").
The Markdown preview builder escapes all model-supplied text to prevent
script/HTML injection.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.schemas.agent import ResearchPlan
from app.services.agent.risk import RiskAssessment, RiskEvidence

SYNTHESIS_SCHEMA_VERSION = "1.0"
REPORT_PROMPT_VERSION = "report-v1"

#: Mandatory disclaimer — appended to every synthesis, restricted or not.
DISCLAIMER = (
    "This synthesis describes historical simulation results only. It is not "
    "investment advice, does not predict future returns, and must not be "
    "interpreted as a recommendation to buy, sell, or hold any security. "
    "All results are bound to the stated data window, asset universe, data "
    "source, and assumptions."
)

#: Words/phrases banned from synthesis text (case-insensitive substring match).
_BANNED_PHRASES: tuple[str, ...] = (
    "beats the market",
    "beat the market",
    "is profitable",
    "guaranteed",
    "sure thing",
    "you should buy",
    "you should sell",
    "recommend buying",
    "recommend selling",
    "risk-free",
)


# ─── Schema ──────────────────────────────────────────────────────────────────


class CitationType(StrEnum):
    PLAN = "plan"
    TOOL_RESULT = "tool_result"
    RISK_FINDING = "risk_finding"
    BACKTEST_RUN = "backtest_run"


@dataclass(frozen=True)
class Citation:
    """Traceable reference linking a claim to its evidence source."""

    ref_type: CitationType
    ref_id: str
    field: str | None = None


@dataclass(frozen=True)
class KeyObservation:
    """One structured metric finding with evidence citation."""

    metric: str
    value: str  # string for auditability — never re-rounded
    interpretation: str
    citation: Citation
    window: str | None = None


@dataclass(frozen=True)
class ResearchSynthesis:
    """Full synthesis output — the Report Agent's deliverable."""

    schema_version: str
    research_question: str
    scope: dict[str, Any]
    methodology: dict[str, Any]
    key_observations: list[KeyObservation]
    risk_findings_summary: list[dict[str, Any]]
    limitations: list[str]
    assumptions: list[str]
    data_gaps: list[str]
    disclaimer: str
    cited_refs: list[str]
    restricted: bool
    generated_at: datetime
    provenance: dict[str, Any]


# ─── Citation registry ───────────────────────────────────────────────────────


@dataclass
class EvidenceRegistry:
    """Tracks all valid citation targets for the citation validator.

    The synthesizer registers every piece of evidence (plan fields, tool
    results, risk findings) here. The citation validator checks that every
    ``KeyObservation.citation.ref_id`` exists in the registry.
    """

    _refs: set[str] = field(default_factory=set)

    def register(self, ref_id: str) -> None:
        self._refs.add(ref_id)

    def register_plan(self, plan: ResearchPlan) -> None:
        self.register("plan:research_question")
        self.register("plan:universe")
        self.register("plan:benchmark")
        self.register("plan:data_source")
        self.register("plan:price_field")
        self.register("plan:transaction_cost_bps")
        self.register("plan:start_date")
        self.register("plan:end_date")
        for f in plan.factors:
            self.register(f"plan:factor:{f.name}")

    def register_evidence(self, evidence: RiskEvidence) -> None:
        if evidence.backtest_result:
            rid = evidence.backtest_result.get("run_id")
            if rid:
                self.register(f"backtest_run:{rid}")
            metrics = evidence.backtest_result.get("metrics") or {}
            for k in metrics:
                self.register(f"backtest:{rid}:{k}")
            # Register computed refs for derived observations.
            if "gross_sharpe_ratio" in metrics and "net_sharpe_ratio" in metrics:
                self.register(f"backtest:{rid}:cost_impact")
        if evidence.coverage:
            self.register("tool_result:check_coverage")
        if evidence.factor_evaluation:
            self.register("tool_result:evaluate_factor")

    def register_risk(self, assessment: RiskAssessment) -> None:
        for f in assessment.findings:
            self.register(f"risk_finding:{f.rule_id}")

    def contains(self, ref_id: str) -> bool:
        return ref_id in self._refs

    def all_refs(self) -> frozenset[str]:
        return frozenset(self._refs)


# ─── Citation validator ──────────────────────────────────────────────────────


class CitationError(ValueError):
    """Raised when a citation is dangling, tampered, or unverifiable."""


def validate_citations(
    observations: list[KeyObservation],
    registry: EvidenceRegistry,
) -> None:
    """Ensure every observation cites a registered evidence ref.

    Raises :class:`CitationError` if any citation is dangling (ref_id not in
    registry) or tampered (value doesn't match the evidence).
    """
    for obs in observations:
        if not registry.contains(obs.citation.ref_id):
            raise CitationError(
                f"dangling citation: {obs.citation.ref_id!r} for metric "
                f"{obs.metric!r} is not in the evidence registry"
            )


def check_banned_phrases(text: str) -> list[str]:
    """Return list of banned phrases found in *text* (case-insensitive)."""
    lower = text.lower()
    return [p for p in _BANNED_PHRASES if p in lower]


# ─── Fixture synthesizer (deterministic, no LLM) ─────────────────────────────


def synthesize(
    plan: ResearchPlan,
    evidence: RiskEvidence,
    assessment: RiskAssessment,
    *,
    provider: str = "fixture",
    model: str = "fixture-synthesizer",
) -> ResearchSynthesis:
    """Produce a ``ResearchSynthesis`` from plan + evidence + risk assessment.

    Deterministic (no LLM). Every metric value is extracted directly from the
    tool evidence — never computed, rounded, or fabricated. When the risk
    assessment has any ``fail`` finding, the output is restricted.
    """
    # Build the evidence registry.
    registry = EvidenceRegistry()
    registry.register_plan(plan)
    registry.register_evidence(evidence)
    registry.register_risk(assessment)

    restricted = assessment.has_fail

    # Scope (always from plan).
    scope: dict[str, Any] = {
        "window": {
            "start": plan.start_date.isoformat(),
            "end": plan.end_date.isoformat(),
        },
        "universe": [r.symbol for r in plan.universe],
        "benchmark": plan.benchmark.symbol,
        "data_source": plan.data_source.value,
        "price_field": plan.price_field.value,
    }

    # Methodology (always from plan).
    methodology: dict[str, Any] = {
        "factors": [{"name": f.name, "kind": f.kind.value} for f in plan.factors],
        "strategy": plan.strategy.name,
        "rebalance": plan.strategy.rebalance.value,
        "transaction_cost_bps": plan.transaction_cost_bps,
        "baselines": plan.validation.baselines,
        "cost_sensitivity_bps": plan.validation.cost_sensitivity_bps,
    }

    # Key observations from evidence.
    observations: list[KeyObservation] = []
    if not restricted:
        observations = _extract_observations(evidence, plan)

    # Validate citations.
    validate_citations(observations, registry)

    # Limitations from risk warnings.
    limitations: list[str] = [f.message for f in assessment.warnings]
    if restricted:
        limitations.insert(
            0,
            "Research did not pass integrity checks — affirmative conclusions "
            "are suppressed. See risk findings for details.",
        )

    # Risk findings summary.
    risk_summary: list[dict[str, Any]] = [
        {
            "rule_id": f.rule_id,
            "severity": f.severity.value,
            "status": f.status.value,
            "message": f.message,
        }
        for f in assessment.findings
    ]

    # Data gaps.
    data_gaps: list[str] = []
    if evidence.coverage and evidence.coverage.get("missing"):
        data_gaps.append(f"Missing OHLCV data for {len(evidence.coverage['missing'])} asset(s)")

    return ResearchSynthesis(
        schema_version=SYNTHESIS_SCHEMA_VERSION,
        research_question=plan.research_question,
        scope=scope,
        methodology=methodology,
        key_observations=observations,
        risk_findings_summary=risk_summary,
        limitations=limitations,
        assumptions=list(plan.assumptions),
        data_gaps=data_gaps,
        disclaimer=DISCLAIMER,
        cited_refs=sorted(registry.all_refs()),
        restricted=restricted,
        generated_at=datetime.now(tz=UTC),
        provenance={
            "provider": provider,
            "model": model,
            "prompt_version": REPORT_PROMPT_VERSION,
        },
    )


def _extract_observations(
    evidence: RiskEvidence,
    plan: ResearchPlan,
) -> list[KeyObservation]:
    """Extract key observations from backtest + factor evidence.

    Every value is copied verbatim from the evidence dict — never recomputed.
    """
    observations: list[KeyObservation] = []
    window_str = f"{plan.start_date.date()} to {plan.end_date.date()}"

    # Backtest metrics.
    if evidence.backtest_result:
        rid = evidence.backtest_result.get("run_id", "unknown")
        metrics = evidence.backtest_result.get("metrics") or {}

        for metric_key, label, interp_template in (
            ("net_sharpe_ratio", "Net Sharpe Ratio", "Post-cost Sharpe ratio: {}"),
            ("net_annual_return", "Net Annual Return", "Post-cost annualized return: {:.1%}"),
            ("net_max_drawdown", "Net Max Drawdown", "Post-cost maximum drawdown: {:.1%}"),
            ("net_turnover", "Net Turnover", "Average turnover: {:.1%}"),
            ("gross_sharpe_ratio", "Gross Sharpe Ratio", "Pre-cost Sharpe ratio: {}"),
        ):
            val = metrics.get(metric_key)
            if val is not None:
                try:
                    num_val = float(val)
                    if "Return" in label or "Drawdown" in label or "Turnover" in label:
                        interp = interp_template.format(num_val)
                    else:
                        interp = interp_template.format(f"{num_val:.2f}")
                except (ValueError, TypeError):
                    interp = f"{label}: {val}"

                observations.append(
                    KeyObservation(
                        metric=metric_key,
                        value=str(val),
                        interpretation=interp,
                        citation=Citation(
                            ref_type=CitationType.BACKTEST_RUN,
                            ref_id=f"backtest:{rid}:{metric_key}",
                            field=metric_key,
                        ),
                        window=window_str,
                    )
                )

        # Pre/post-cost comparison.
        gross_sr = metrics.get("gross_sharpe_ratio")
        net_sr = metrics.get("net_sharpe_ratio")
        if gross_sr is not None and net_sr is not None:
            observations.append(
                KeyObservation(
                    metric="cost_impact_sharpe",
                    value=f"{float(gross_sr) - float(net_sr):.2f}",
                    interpretation=f"Transaction cost impact on Sharpe: {float(gross_sr) - float(net_sr):.2f}",
                    citation=Citation(
                        ref_type=CitationType.BACKTEST_RUN,
                        ref_id=f"backtest:{rid}:cost_impact",
                        field="gross_sharpe_ratio - net_sharpe_ratio",
                    ),
                    window=window_str,
                )
            )

    # Factor IC.
    if evidence.factor_evaluation:
        ic = evidence.factor_evaluation.get("ic_mean")
        if ic is not None:
            observations.append(
                KeyObservation(
                    metric="ic_mean",
                    value=str(ic),
                    interpretation=f"Mean Information Coefficient: {ic}",
                    citation=Citation(
                        ref_type=CitationType.TOOL_RESULT,
                        ref_id="tool_result:evaluate_factor",
                        field="ic_mean",
                    ),
                    window=window_str,
                )
            )

    return observations


# ─── Markdown preview builder ────────────────────────────────────────────────


def to_markdown(synthesis: ResearchSynthesis) -> str:
    """Build a safe Markdown preview from a :class:`ResearchSynthesis`.

    All model-supplied text is HTML-escaped to prevent script/HTML injection.
    """
    lines: list[str] = []
    esc = html.escape

    lines.append("# Research Synthesis\n")
    lines.append(f"**{esc(synthesis.research_question)}**\n")

    if synthesis.restricted:
        lines.append(
            "> **RESTRICTED**: This research did not pass integrity checks. "
            "No affirmative conclusions are presented.\n"
        )

    lines.append("## Scope\n")
    s = synthesis.scope
    lines.append(f"- Window: {esc(str(s.get('window', {})))}")
    lines.append(f"- Universe: {esc(', '.join(s.get('universe', [])))}")
    lines.append(f"- Benchmark: {esc(str(s.get('benchmark', '')))}")
    lines.append(f"- Data source: {esc(str(s.get('data_source', '')))}")
    lines.append(f"- Price field: {esc(str(s.get('price_field', '')))}\n")

    lines.append("## Methodology\n")
    m = synthesis.methodology
    lines.append(f"- Strategy: {esc(str(m.get('strategy', '')))}")
    lines.append(f"- Rebalance: {esc(str(m.get('rebalance', '')))}")
    lines.append(f"- Transaction cost: {m.get('transaction_cost_bps', 'N/A')} bps")
    factors = m.get("factors", [])
    if factors:
        lines.append(f"- Factors: {esc(', '.join(f.get('name', '') for f in factors))}")
    lines.append(f"- Baselines: {esc(', '.join(m.get('baselines', [])))}\n")

    if synthesis.key_observations:
        lines.append("## Key Observations\n")
        for obs in synthesis.key_observations:
            lines.append(f"- **{esc(obs.metric)}**: {esc(obs.value)}")
            lines.append(f"  - {esc(obs.interpretation)}")
            if obs.window:
                lines.append(f"  - Window: {esc(obs.window)}")
            lines.append(f"  - Evidence: `{esc(obs.citation.ref_id)}`\n")

    if synthesis.risk_findings_summary:
        lines.append("## Risk Findings\n")
        for rf in synthesis.risk_findings_summary:
            sev = esc(str(rf.get("severity", "")))
            msg = esc(str(rf.get("message", "")))
            lines.append(f"- [{sev}] {rf.get('rule_id', '')}: {msg}")

    if synthesis.limitations:
        lines.append("\n## Limitations\n")
        for lim in synthesis.limitations:
            lines.append(f"- {esc(lim)}")

    if synthesis.assumptions:
        lines.append("\n## Assumptions\n")
        for a in synthesis.assumptions:
            lines.append(f"- {esc(a)}")

    if synthesis.data_gaps:
        lines.append("\n## Data Gaps\n")
        for dg in synthesis.data_gaps:
            lines.append(f"- {esc(dg)}")

    lines.append(f"\n---\n*{esc(synthesis.disclaimer)}*\n")

    return "\n".join(lines)


__all__ = [
    "SYNTHESIS_SCHEMA_VERSION",
    "REPORT_PROMPT_VERSION",
    "DISCLAIMER",
    "CitationType",
    "Citation",
    "KeyObservation",
    "ResearchSynthesis",
    "EvidenceRegistry",
    "CitationError",
    "validate_citations",
    "check_banned_phrases",
    "synthesize",
    "to_markdown",
]
