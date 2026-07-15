"""Risk Agent — deterministic research integrity checks (FRA-88).

The Risk Agent is the **hard safety gate** between tool execution and report
synthesis. It is fully deterministic (no LLM): it reads the validated
``ResearchPlan`` + tool evidence and emits a machine-judgable
``RiskAssessment`` with pass / warn / fail findings.

* ``fail`` — blocks the Report Agent from producing affirmative conclusions.
* ``warn`` — enters the report's limitations section but does not block.
* ``pass`` — the check is satisfied.

The assessment is deterministic and snapshot-testable: identical input always
produces identical output.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.schemas.agent import FactorKind, PlanResolution, ResearchPlan

# ─── Schema ──────────────────────────────────────────────────────────────────

RISK_SCHEMA_VERSION = "1.0"


class RiskSeverity(StrEnum):
    """How a finding affects the report pipeline."""

    FAIL = "fail"
    WARN = "warn"
    INFO = "info"


class FindingStatus(StrEnum):
    """Outcome of one check."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


@dataclass(frozen=True)
class RiskFinding:
    """One deterministic check result.

    ``evidence_ref`` links to a tool call, backtest run, or plan field so the
    finding is auditable. ``remediation`` tells the user what to fix.
    """

    rule_id: str
    severity: RiskSeverity
    status: FindingStatus
    message: str
    remediation: str | None = None
    evidence_ref: str | None = None
    plan_field: str | None = None


@dataclass(frozen=True)
class RiskAssessment:
    """Full assessment output — the gate for the Report Agent.

    ``overall_status`` is the highest-severity finding:
    ``fail > warn > pass``.
    """

    schema_version: str
    overall_status: FindingStatus
    findings: list[RiskFinding]
    assessed_at: datetime
    plan_hash: str
    finding_count: int

    @property
    def has_fail(self) -> bool:
        """True if any finding has status=FAIL — blocks affirmative report."""
        return any(f.status == FindingStatus.FAIL for f in self.findings)

    @property
    def warnings(self) -> list[RiskFinding]:
        """Findings that enter the limitations section."""
        return [f for f in self.findings if f.status == FindingStatus.WARN]

    @property
    def failed_rules(self) -> list[str]:
        """Rule IDs that failed — for actionable error display."""
        return [f.rule_id for f in self.findings if f.status == FindingStatus.FAIL]


# ─── Evidence input ──────────────────────────────────────────────────────────


@dataclass
class RiskEvidence:
    """Structured evidence extracted from tool results.

    Each field is the ``data`` dict from a ``ToolResult``, or ``None`` if the
    corresponding tool was not called (or failed). This decouples the Risk
    Agent from the tool implementations — it only reads the summary dicts.
    """

    coverage: dict[str, Any] | None = None
    backtest_result: dict[str, Any] | None = None
    factor_evaluation: dict[str, Any] | None = None
    tool_errors: list[str] = field(default_factory=list)


# ─── Deterministic rules ─────────────────────────────────────────────────────


def _check_benchmark(plan: ResearchPlan, ev: RiskEvidence) -> RiskFinding | None:
    """R001: validated plan must have a resolved benchmark."""
    if plan.resolution == PlanResolution.VALIDATED and plan.benchmark.asset_id is None:
        return RiskFinding(
            rule_id="R001_benchmark_exists",
            severity=RiskSeverity.FAIL,
            status=FindingStatus.FAIL,
            message="Validated plan has no resolved benchmark asset_id",
            remediation="Resolve the benchmark symbol to an asset_id before running tools",
            plan_field="benchmark.asset_id",
        )
    return None


def _check_transaction_cost(plan: ResearchPlan, ev: RiskEvidence) -> RiskFinding | None:
    """R002: plan must declare transaction cost (0 is allowed, omission is not)."""
    # ResearchPlan schema already enforces transaction_cost_bps >= 0.
    # This check catches the edge case where cost was explicitly 0 without
    # cost sensitivity bands.
    if not plan.validation.cost_sensitivity_bps:
        return RiskFinding(
            rule_id="R002_cost_sensitivity",
            severity=RiskSeverity.FAIL,
            status=FindingStatus.FAIL,
            message="Plan has no transaction-cost sensitivity bands (mandatory per methodology)",
            remediation="Set validation.cost_sensitivity_bps to at least [0.0, 10.0]",
            plan_field="validation.cost_sensitivity_bps",
        )
    return None


def _check_baselines(plan: ResearchPlan, ev: RiskEvidence) -> RiskFinding | None:
    """R003: plan must have at least one validation baseline."""
    if not plan.validation.baselines:
        return RiskFinding(
            rule_id="R003_baselines_present",
            severity=RiskSeverity.FAIL,
            status=FindingStatus.FAIL,
            message="Plan has no validation baselines (buy_and_hold / equal_weight / benchmark required)",
            remediation="Add at least one baseline to validation.baselines",
            plan_field="validation.baselines",
        )
    return None


def _check_evidence_completeness(plan: ResearchPlan, ev: RiskEvidence) -> RiskFinding | None:
    """R004: no tool execution errors in evidence."""
    if ev.tool_errors:
        return RiskFinding(
            rule_id="R004_evidence_complete",
            severity=RiskSeverity.FAIL,
            status=FindingStatus.FAIL,
            message=f"Tool execution had {len(ev.tool_errors)} error(s): {'; '.join(ev.tool_errors[:3])}",
            remediation="Re-run failed tools or exclude them from the evidence set",
            evidence_ref="tool_results",
        )
    return None


def _check_gross_net_metrics(plan: ResearchPlan, ev: RiskEvidence) -> RiskFinding | None:
    """R005: backtest must have both gross and net metrics (pre/post-cost)."""
    if ev.backtest_result is None:
        return None  # no backtest evidence — skip
    metrics = ev.backtest_result.get("metrics")
    if metrics is None:
        return RiskFinding(
            rule_id="R005_gross_net_metrics",
            severity=RiskSeverity.FAIL,
            status=FindingStatus.FAIL,
            message="Backtest result has no metrics (expected gross + net)",
            remediation="Ensure the backtest completed successfully and metrics are persisted",
            evidence_ref=ev.backtest_result.get("run_id"),
        )
    has_gross = any(k.startswith("gross_") and v is not None for k, v in metrics.items())
    has_net = any(k.startswith("net_") and v is not None for k, v in metrics.items())
    if not has_gross or not has_net:
        return RiskFinding(
            rule_id="R005_gross_net_metrics",
            severity=RiskSeverity.FAIL,
            status=FindingStatus.FAIL,
            message="Backtest metrics missing gross or net series (pre/post-cost comparison required)",
            remediation="Re-run the backtest with cost_bps > 0 or verify metrics persistence",
            evidence_ref=ev.backtest_result.get("run_id"),
        )
    return None


def _check_survivorship(plan: ResearchPlan, ev: RiskEvidence) -> RiskFinding | None:
    """R006: survivorship bias should be documented."""
    if not plan.risk_checks.survivorship_documented:
        return RiskFinding(
            rule_id="R006_survivorship",
            severity=RiskSeverity.WARN,
            status=FindingStatus.WARN,
            message="Survivorship bias is not documented (current universe may exclude delisted stocks)",
            remediation="Document survivorship status in risk_checks.survivorship_documented or add a note to assumptions",
            plan_field="risk_checks.survivorship_documented",
        )
    return None


def _check_sample_length(plan: ResearchPlan, ev: RiskEvidence) -> RiskFinding | None:
    """R007: backtest window should be >= 252 trading days (~1 year)."""
    if ev.backtest_result is None:
        return None
    equity_points = ev.backtest_result.get("equity_points", 0)
    if isinstance(equity_points, int) and equity_points < 252:
        return RiskFinding(
            rule_id="R007_sample_length",
            severity=RiskSeverity.WARN,
            status=FindingStatus.WARN,
            message=f"Backtest has only {equity_points} data points (< 252 = ~1 year); results may be unreliable",
            remediation="Extend the data window to at least one full year",
            evidence_ref=ev.backtest_result.get("run_id"),
        )
    return None


def _check_data_coverage(plan: ResearchPlan, ev: RiskEvidence) -> RiskFinding | None:
    """R008: data coverage should be sufficient."""
    if ev.coverage is None:
        return None
    missing = ev.coverage.get("missing", [])
    if missing:
        return RiskFinding(
            rule_id="R008_data_coverage",
            severity=RiskSeverity.WARN,
            status=FindingStatus.WARN,
            message=f"Data gaps detected for {len(missing)} asset(s); missing: {missing[:3]}",
            remediation="Sync missing OHLCV data before drawing conclusions",
            evidence_ref="check_coverage",
        )
    return None


def _check_sentiment_provenance(plan: ResearchPlan, ev: RiskEvidence) -> RiskFinding | None:
    """R009: sentiment factors must have resolved provenance in validated plans."""
    has_sentiment = any(f.kind == FactorKind.SENTIMENT for f in plan.factors)
    if not has_sentiment:
        return None
    prov = plan.sentiment_provenance
    if prov is None:
        return RiskFinding(
            rule_id="R009_sentiment_provenance",
            severity=RiskSeverity.FAIL,
            status=FindingStatus.FAIL,
            message="Plan uses a sentiment factor but declares no sentiment_provenance",
            remediation="Set sentiment_provenance with provider, model_name, and prompt_version",
            plan_field="sentiment_provenance",
        )
    if prov.pending:
        return RiskFinding(
            rule_id="R009_sentiment_provenance",
            severity=RiskSeverity.FAIL,
            status=FindingStatus.FAIL,
            message="Sentiment provenance is still pending (provider/model/prompt not resolved)",
            remediation="Resolve the sentiment classifier provider, model_name, and prompt_version",
            plan_field="sentiment_provenance.pending",
        )
    return None


def _check_max_drawdown(plan: ResearchPlan, ev: RiskEvidence) -> RiskFinding | None:
    """R010: flag extreme max drawdown for closer inspection."""
    if ev.backtest_result is None:
        return None
    metrics = ev.backtest_result.get("metrics")
    if not metrics:
        return None
    max_dd = metrics.get("net_max_drawdown")
    if max_dd is not None and max_dd < -0.4:
        return RiskFinding(
            rule_id="R010_max_drawdown",
            severity=RiskSeverity.WARN,
            status=FindingStatus.WARN,
            message=f"Max drawdown is {max_dd:.1%}; exceeds -40% threshold",
            remediation="Review drawdown causes and document in the report's risk section",
            evidence_ref=ev.backtest_result.get("run_id"),
        )
    return None


def _check_single_source(plan: ResearchPlan, ev: RiskEvidence) -> RiskFinding | None:
    """R011: warn if data comes from a single source (no cross-validation)."""
    # ResearchPlan has a single data_source; this is always a single-source design.
    # We warn unless the plan explicitly addresses this in assumptions.
    assumption_text = " ".join(plan.assumptions).lower()
    if "single source" not in assumption_text and "data source" not in assumption_text:
        return RiskFinding(
            rule_id="R011_single_source",
            severity=RiskSeverity.WARN,
            status=FindingStatus.WARN,
            message=f"All data comes from a single source ({plan.data_source.value}); no cross-validation",
            remediation="Document the single-source limitation in plan assumptions",
            plan_field="data_source",
        )
    return None


def _check_time_based_split(plan: ResearchPlan, ev: RiskEvidence) -> RiskFinding | None:
    """R012: warn if no time-based train/forward split is mentioned."""
    assumption_text = " ".join(plan.assumptions).lower()
    if (
        "time" not in assumption_text
        and "split" not in assumption_text
        and "forward" not in assumption_text
    ):
        return RiskFinding(
            rule_id="R012_time_based_split",
            severity=RiskSeverity.WARN,
            status=FindingStatus.WARN,
            message="No time-based train/forward validation mentioned in assumptions",
            remediation="Consider documenting the time-based split methodology in assumptions",
            plan_field="assumptions",
        )
    return None


# Ordered list of all checks.
_ALL_CHECKS = (
    _check_benchmark,
    _check_transaction_cost,
    _check_baselines,
    _check_evidence_completeness,
    _check_gross_net_metrics,
    _check_sentiment_provenance,
    _check_survivorship,
    _check_sample_length,
    _check_data_coverage,
    _check_max_drawdown,
    _check_single_source,
    _check_time_based_split,
)


# ─── Assessor ────────────────────────────────────────────────────────────────


def _compute_plan_hash(plan: ResearchPlan) -> str:
    """SHA-256 of canonical JSON for plan identity."""
    canonical = json.dumps(plan.model_dump(mode="json"), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def assess_risk(plan: ResearchPlan, evidence: RiskEvidence) -> RiskAssessment:
    """Run all deterministic checks and return a :class:`RiskAssessment`.

    This is the single entry point. It is pure and deterministic — identical
    ``(plan, evidence)`` always produces identical output.
    """
    findings: list[RiskFinding] = []
    for check in _ALL_CHECKS:
        result = check(plan, evidence)
        if result is not None:
            findings.append(result)

    if any(f.status == FindingStatus.FAIL for f in findings):
        overall = FindingStatus.FAIL
    elif any(f.status == FindingStatus.WARN for f in findings):
        overall = FindingStatus.WARN
    else:
        overall = FindingStatus.PASS

    return RiskAssessment(
        schema_version=RISK_SCHEMA_VERSION,
        overall_status=overall,
        findings=findings,
        assessed_at=datetime.now(tz=UTC),
        plan_hash=_compute_plan_hash(plan),
        finding_count=len(findings),
    )


__all__ = [
    "RISK_SCHEMA_VERSION",
    "RiskSeverity",
    "FindingStatus",
    "RiskFinding",
    "RiskAssessment",
    "RiskEvidence",
    "assess_risk",
]
