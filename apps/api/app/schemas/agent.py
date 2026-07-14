"""Versioned contract for the Week 5 LLM research agent (FRA-84).

This module is the **single source of truth** for the structured contract shared
by the Research Planner, the Data / Factor / Backtest / Risk / Report agents, and
the run/step/tool-call state machine. It is a *contract spike*: it defines types
and validation only — it does **not** call an LLM, run a backtest, or touch the
database. Persistence is FRA-85; the Planner is FRA-86; tool execution adapters
are FRA-87 — all of which consume these types.

Design rules enforced here (acceptance criteria of FRA-84):

* The schema is versioned via ``SCHEMA_VERSION``; an unknown version is rejected.
* ``ResearchPlan`` binds the full data window, asset universe, source, price
  field, assumptions and requested outputs — nothing is left implicit.
* ``universe`` / ``benchmark`` distinguish the user-supplied ``symbol`` from the
  resolved ``asset_id``; a ``validated`` plan may not carry unresolved symbols
  (no free-text escape hatch around asset resolution).
* Factors, strategies and tools are validated against **allowlists** that mirror
  the live registries (``FACTOR_REGISTRY``, strategy registry). The model may
  never generate or execute arbitrary Python / SQL / shell.
* ``transaction_cost_bps`` and ``validation.baselines`` are mandatory — a plan
  with no transaction cost and no baseline is rejected.
* A sentiment factor forces a ``SentimentProvenance`` declaring
  provider/model/prompt_version (or an explicit ``pending`` deferral).
* ``AgentRun`` / ``AgentStep`` / ``ToolCall`` share a state machine whose
  terminal states (``succeeded`` / ``failed`` / ``canceled``) are irreversible.

The Pydantic models below are mirrored 1:1 by ``packages/shared`` (Zod) and by
the canonical fixture ``packages/shared/src/__fixtures__/research-plan.canonical.json``;
``tests/test_agent_contracts.py`` and the web vitest contract test both validate
that same fixture to prevent frontend/backend drift.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ─── Schema versioning ───────────────────────────────────────────────────────

#: Canonical version of the ``ResearchPlan`` contract. Bump on any breaking
#: change to field names, enum members, or validation semantics; the Planner
#: must emit this version and persistence (FRA-85) must store it verbatim.
SCHEMA_VERSION: str = "1.0"

#: Agent roles that may appear as a step ``agent_role`` or as a tool caller.
#: Mirrors `docs/agent-design.md` §Agent Roles.
AGENT_ROLES: frozenset[str] = frozenset(
    {
        "research_planner",
        "data_agent",
        "factor_agent",
        "backtest_agent",
        "risk_agent",
        "report_agent",
    }
)

# ─── Allowlists (mirror the live registries) ─────────────────────────────────
#
# These frozensets are the only factor / strategy / tool names the agent may
# emit or invoke. They are intentionally copied (not imported) from the service
# layer so the contract stays decoupled from runtime imports; the contract tests
# assert they stay in sync with ``FACTOR_REGISTRY`` / the strategy registry.

#: Technical factor names — must match ``app.services.factors.service.FACTOR_REGISTRY``.
TECHNICAL_FACTOR_NAMES: frozenset[str] = frozenset(
    {
        "momentum_21",
        "momentum_63",
        "momentum_126",
        "reversal_5",
        "reversal_21",
        "macd_hist",
        "rsi_14",
        "volatility_20d",
        "volatility_63d",
    }
)

#: Strategy template names — must match ``app.services.backtest.strategies.registry``.
STRATEGY_NAMES: frozenset[str] = frozenset(
    {
        "buy_hold",
        "equal_weight",
        "factor",
        "ma_crossover",
        "momentum",
        "reversal",
        "sentiment_tech",
    }
)

#: Validation baseline kinds. ``benchmark`` means "use ``ResearchPlan.benchmark``".
#: Semantic tags (not raw symbols) keep baseline selection auditable.
VALIDATION_BASELINE_KINDS: frozenset[str] = frozenset({"buy_and_hold", "equal_weight", "benchmark"})

#: Default transaction-cost sensitivity bands (bps), per
#: ``docs/backtesting-methodology.md`` (transaction-cost sensitivity is mandatory).
DEFAULT_COST_SENSITIVITY_BPS: tuple[float, ...] = (0.0, 5.0, 10.0, 25.0)


# ─── Enums ───────────────────────────────────────────────────────────────────


class DataSource(StrEnum):
    """Allowed OHLCV / news data sources."""

    YFINANCE = "yfinance"
    POLYGON = "polygon"
    ALPHA_VANTAGE = "alpha_vantage"
    STOOQ = "stooq"
    OPENBB = "openbb"


class PriceField(StrEnum):
    """Price field used for signals & equity, mirrors the backtest engine."""

    RAW = "raw"
    ADJUSTED = "adjusted"


class RebalanceFrequency(StrEnum):
    """Rebalance cadence, mirrors the backtest engine."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class PlanResolution(StrEnum):
    """Lifecycle of a plan before it is queued.

    ``draft`` — symbols present, ``asset_id`` may be unresolved (the Planner is
        still negotiating the universe).
    ``validated`` — every ``AssetRef`` carries a resolved ``asset_id``; the plan
        is ready to enqueue. The state machine forbids ``queued`` from ``draft``.
    """

    DRAFT = "draft"
    VALIDATED = "validated"


class FactorKind(StrEnum):
    """Factor family. ``sentiment`` factors trigger provenance requirements."""

    TECHNICAL = "technical"
    SENTIMENT = "sentiment"


class ToolRole(StrEnum):
    """Which agent role owns a tool. Mirrors the five tool categories."""

    DATA = "data"
    FACTOR = "factor"
    BACKTEST = "backtest"
    RISK = "risk"
    REPORT = "report"


# ─── Run / step state machine ────────────────────────────────────────────────


class AgentRunStatus(StrEnum):
    """States for an ``AgentRun``.

    Note: this intentionally uses ``succeeded`` (past tense) per the FRA-84 spec,
    distinct from ``BacktestRun.status`` which uses ``success``. The two are
    separate lifecycles; FRA-85 maps between them at the persistence layer.
    """

    DRAFT = "draft"
    VALIDATED = "validated"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class AgentStepStatus(StrEnum):
    """States for an ``AgentStep`` / ``ToolCall``.

    Steps and tool calls skip the plan-level ``draft`` / ``validated`` phases —
    they only exist once a run is queued — so their state machine is the
    ``queued → running → terminal`` subset.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


#: Terminal run statuses — once reached, no further transition is legal.
TERMINAL_RUN_STATUSES: frozenset[AgentRunStatus] = frozenset(
    {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED, AgentRunStatus.CANCELED}
)

#: Legal transitions for an ``AgentRun``. Terminal states map to an empty set,
#: i.e. they are irreversible (acceptance: "terminal 状态不可回退").
RUN_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.DRAFT: frozenset({AgentRunStatus.VALIDATED, AgentRunStatus.CANCELED}),
    AgentRunStatus.VALIDATED: frozenset({AgentRunStatus.QUEUED, AgentRunStatus.CANCELED}),
    AgentRunStatus.QUEUED: frozenset({AgentRunStatus.RUNNING, AgentRunStatus.CANCELED}),
    AgentRunStatus.RUNNING: frozenset(
        {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED, AgentRunStatus.CANCELED}
    ),
    AgentRunStatus.SUCCEEDED: frozenset(),
    AgentRunStatus.FAILED: frozenset(),
    AgentRunStatus.CANCELED: frozenset(),
}

#: Legal transitions for an ``AgentStep`` / ``ToolCall``.
STEP_TRANSITIONS: dict[AgentStepStatus, frozenset[AgentStepStatus]] = {
    AgentStepStatus.QUEUED: frozenset({AgentStepStatus.RUNNING, AgentStepStatus.CANCELED}),
    AgentStepStatus.RUNNING: frozenset(
        {AgentStepStatus.SUCCEEDED, AgentStepStatus.FAILED, AgentStepStatus.CANCELED}
    ),
    AgentStepStatus.SUCCEEDED: frozenset(),
    AgentStepStatus.FAILED: frozenset(),
    AgentStepStatus.CANCELED: frozenset(),
}


class IllegalStateTransitionError(ValueError):
    """Raised when a run/step/tool-call transition is not in the allowlist."""


def assert_run_transition(current: AgentRunStatus, target: AgentRunStatus) -> None:
    """Validate an ``AgentRun`` state transition; raise if disallowed.

    Terminal states (``succeeded`` / ``failed`` / ``canceled``) have no legal
    outgoing transition, so any attempt to move out of them raises — this is the
    "terminal 状态不可回退" acceptance criterion.
    """
    if target not in RUN_TRANSITIONS[current]:
        raise IllegalStateTransitionError(
            f"illegal run transition {current.value!r} -> {target.value!r}; "
            f"legal targets from {current.value!r}: "
            f"{sorted(s.value for s in RUN_TRANSITIONS[current])}"
        )


def assert_step_transition(current: AgentStepStatus, target: AgentStepStatus) -> None:
    """Validate an ``AgentStep`` / ``ToolCall`` transition; raise if disallowed."""
    if target not in STEP_TRANSITIONS[current]:
        raise IllegalStateTransitionError(
            f"illegal step transition {current.value!r} -> {target.value!r}; "
            f"legal targets from {current.value!r}: "
            f"{sorted(s.value for s in STEP_TRANSITIONS[current])}"
        )


# ─── Plan component schemas ──────────────────────────────────────────────────


class AssetRef(BaseModel):
    """A universe / benchmark member.

    Distinguishes the user-supplied ``symbol`` (free text from the hypothesis)
    from the resolved ``asset_id`` (UUID of a row in ``assets``). A ``validated``
    plan requires every ``AssetRef`` to carry an ``asset_id`` — there is no
    free-text escape hatch around asset resolution (acceptance criterion).
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=32, description="Ticker / input symbol.")
    asset_id: uuid.UUID | None = Field(
        default=None,
        description="Resolved asset UUID; required once the plan is `validated`.",
    )


class FactorSpec(BaseModel):
    """A factor the plan depends on.

    ``technical`` factors must use a name in :data:`TECHNICAL_FACTOR_NAMES`.
    ``sentiment`` factors must use the canonical name ``sentiment`` and force a
    :class:`SentimentProvenance` on the plan.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    kind: FactorKind = FactorKind.TECHNICAL
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameter snapshot for reproducibility (§11.3 第 6 条).",
    )


class SentimentProvenance(BaseModel):
    """Reproducibility provenance for any sentiment factor in the plan.

    Either the full ``(provider, model_name, prompt_version)`` triple is present,
    or ``pending`` is set to defer resolution (e.g. the Planner has not yet
    picked a classifier). A validated plan may not stay ``pending``.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, description="News provider key.")
    model_name: str | None = Field(default=None, description="Classifier model name.")
    prompt_version: str | None = Field(default=None, description="Prompt template version.")
    pending: bool = Field(
        default=False,
        description="True defers provider/model/prompt resolution (draft only).",
    )


class StrategyConfig(BaseModel):
    """Strategy template + parameters + rebalance cadence.

    ``name`` must be in :data:`STRATEGY_NAMES`; ``params`` is passed verbatim to
    the strategy constructor (e.g. ``{"fast": 5, "slow": 20}``).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    rebalance: RebalanceFrequency


class ValidationConfig(BaseModel):
    """How the strategy is compared and stress-tested.

    ``baselines`` are semantic tags from :data:`VALIDATION_BASELINE_KINDS`;
    ``cost_sensitivity_bps`` are the transaction-cost bands the risk agent must
    sweep (mandatory per the backtesting methodology).
    """

    model_config = ConfigDict(extra="forbid")

    baselines: list[str] = Field(
        min_length=1, description="Non-empty; each ∈ buy_and_hold | equal_weight | benchmark."
    )
    metrics: list[str] = Field(
        default_factory=lambda: ["annual_return", "sharpe", "max_drawdown", "turnover"],
        min_length=1,
    )
    cost_sensitivity_bps: list[float] = Field(
        default_factory=lambda: list(DEFAULT_COST_SENSITIVITY_BPS),
        min_length=1,
        description="Transaction-cost bands (bps) to sweep.",
    )


class RiskChecksConfig(BaseModel):
    """Risk-gate toggles. ``transaction_cost_sensitivity`` is mandatory-on."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    transaction_cost_sensitivity: bool = Field(
        default=True, description="Must run pre/post-cost (backtesting methodology)."
    )
    survivorship_documented: bool = Field(
        default=False,
        description="If survivorship bias is unavoidable, the report must document it.",
    )
    max_drawdown_warning: float | None = Field(
        default=None,
        description="Optional drawdown threshold (e.g. -0.3) that flags the run.",
    )


# ─── ResearchPlan (the canonical contract) ───────────────────────────────────


class ResearchPlan(BaseModel):
    """A versioned, fully-bound research plan.

    This is the contract every Week 5 agent consumes. Field-level constraints
    (``min_length``, ``ge``) plus the :meth:`_validate_invariants` cross-field
    validator enforce the FRA-84 acceptance criteria. ``extra="forbid"`` rejects
    unknown fields so the model can never smuggle in ad-hoc configuration.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=SCHEMA_VERSION)
    research_question: str = Field(min_length=1)

    resolution: PlanResolution = PlanResolution.DRAFT
    universe: list[AssetRef] = Field(min_length=1)
    benchmark: AssetRef
    data_source: DataSource
    start_date: datetime
    end_date: datetime
    price_field: PriceField

    factors: list[FactorSpec] = Field(default_factory=list)
    sentiment_provenance: SentimentProvenance | None = None

    strategy: StrategyConfig
    transaction_cost_bps: float = Field(
        ge=0.0,
        description="Single-side proportional cost in bps; explicit 0 is allowed, "
        "omission is not (acceptance: 无交易成本被拒).",
    )

    validation: ValidationConfig
    risk_checks: RiskChecksConfig = Field(default_factory=RiskChecksConfig)

    assumptions: list[str] = Field(
        min_length=1, description="Stated assumptions; every conclusion binds to these."
    )
    requested_outputs: list[str] = Field(
        min_length=1, description="Requested deliverables (e.g. memo, equity curve, IC table)."
    )

    @model_validator(mode="after")
    def _validate_invariants(self) -> ResearchPlan:
        # 1. Schema version lock.
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {self.schema_version!r}; expected {SCHEMA_VERSION!r}"
            )

        # 2. Data window ordering.
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")

        # 3. Validated plans must have every asset resolved (no free-text escape).
        if self.resolution == PlanResolution.VALIDATED:
            unresolved: list[str] = []
            if self.benchmark.asset_id is None:
                unresolved.append(f"benchmark:{self.benchmark.symbol}")
            for ref in self.universe:
                if ref.asset_id is None:
                    unresolved.append(ref.symbol)
            if unresolved:
                raise ValueError(
                    "validated plan has unresolved asset(s); missing asset_id for: "
                    + ", ".join(unresolved)
                )

        # 4. Factor allowlist + sentiment provenance.
        has_sentiment = False
        for factor in self.factors:
            if factor.kind == FactorKind.TECHNICAL:
                if factor.name not in TECHNICAL_FACTOR_NAMES:
                    raise ValueError(
                        f"unknown technical factor {factor.name!r}; expected one of "
                        f"{sorted(TECHNICAL_FACTOR_NAMES)}"
                    )
            else:  # FactorKind.SENTIMENT
                has_sentiment = True
                if factor.name != "sentiment":
                    raise ValueError(
                        f"sentiment factor must use canonical name 'sentiment', got {factor.name!r}"
                    )
        if has_sentiment:
            prov = self.sentiment_provenance
            if prov is None:
                raise ValueError(
                    "plan uses a sentiment factor but declares no sentiment_provenance"
                )
            resolved = bool(prov.provider and prov.model_name and prov.prompt_version)
            if not resolved and not prov.pending:
                raise ValueError(
                    "sentiment_provenance must set provider/model_name/prompt_version "
                    "or mark pending=true"
                )
            if prov.pending and self.resolution == PlanResolution.VALIDATED:
                raise ValueError("validated plan may not keep sentiment_provenance pending")

        # 5. Strategy allowlist.
        if self.strategy.name not in STRATEGY_NAMES:
            raise ValueError(
                f"unknown strategy {self.strategy.name!r}; expected one of {sorted(STRATEGY_NAMES)}"
            )

        # 6. Validation baseline allowlist.
        for baseline in self.validation.baselines:
            if baseline not in VALIDATION_BASELINE_KINDS:
                raise ValueError(
                    f"unknown validation baseline {baseline!r}; expected one of "
                    f"{sorted(VALIDATION_BASELINE_KINDS)}"
                )

        return self


# ─── Tool catalog (the allowlist of invocable tools) ─────────────────────────


class ToolSpec(BaseModel):
    """Declarative spec for one tool the agent may call.

    The catalog is the single allowlist of invocable tools — anything not listed
    in :data:`TOOL_CATALOG` is rejected by the Orchestrator. ``input_schema`` /
    ``output_schema`` name the Pydantic models (string refs) for documentation;
    runtime validation is the adapter's job (FRA-87).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    role: ToolRole
    description: str
    allowed_callers: tuple[str, ...]
    input_schema: str
    output_schema: str
    has_side_effects: bool
    idempotent: bool
    timeout_seconds: int = Field(ge=1)


#: The tool catalog. Covers the Data / Factor / Backtest / Risk / Report roles
#: (acceptance: "tool catalog 覆盖 Data / Factor / Backtest / Risk / Report 五类角色").
#: ``has_side_effects`` flags anything that writes the DB or calls an external
#: service; ``idempotent`` flags whether repeating the call is safe.
TOOL_CATALOG: dict[str, ToolSpec] = {
    # --- Data role ---
    "resolve_assets": ToolSpec(
        name="resolve_assets",
        role=ToolRole.DATA,
        description="Map input symbols to asset UUIDs (assets table lookup).",
        allowed_callers=("research_planner", "data_agent"),
        input_schema="list[str]",
        output_schema="list[AssetRef]",
        has_side_effects=False,
        idempotent=True,
        timeout_seconds=30,
    ),
    "sync_ohlcv": ToolSpec(
        name="sync_ohlcv",
        role=ToolRole.DATA,
        description="Fetch & upsert OHLCV bars for a universe + window.",
        allowed_callers=("data_agent",),
        input_schema="SyncRequest",
        output_schema="SyncResponse",
        has_side_effects=True,
        idempotent=True,
        timeout_seconds=600,
    ),
    "sync_news": ToolSpec(
        name="sync_news",
        role=ToolRole.DATA,
        description="Fetch & upsert news items for a universe + window.",
        allowed_callers=("data_agent",),
        input_schema="NewsSyncRequest",
        output_schema="NewsSyncResponse",
        has_side_effects=True,
        idempotent=True,
        timeout_seconds=600,
    ),
    # --- Factor role ---
    "compute_factor": ToolSpec(
        name="compute_factor",
        role=ToolRole.FACTOR,
        description="Compute factor values and idempotently upsert into factor_values.",
        allowed_callers=("factor_agent",),
        input_schema="FactorComputeRequest",
        output_schema="FactorComputeResponse",
        has_side_effects=True,
        idempotent=True,
        timeout_seconds=600,
    ),
    "evaluate_factor": ToolSpec(
        name="evaluate_factor",
        role=ToolRole.FACTOR,
        description="Read-only IC / quantile evaluation of a stored factor.",
        allowed_callers=("factor_agent", "risk_agent"),
        input_schema="QuantileBacktestRequest",
        output_schema="ICResponse | QuantileBacktestResponse",
        has_side_effects=False,
        idempotent=True,
        timeout_seconds=300,
    ),
    # --- Backtest role ---
    "run_backtest": ToolSpec(
        name="run_backtest",
        role=ToolRole.BACKTEST,
        description="Enqueue + run a single backtest (persisted as a BacktestRun).",
        allowed_callers=("backtest_agent",),
        input_schema="BacktestCreateRequest",
        output_schema="BacktestEnqueueResponse",
        has_side_effects=True,
        idempotent=False,
        timeout_seconds=900,
    ),
    "run_comparison": ToolSpec(
        name="run_comparison",
        role=ToolRole.BACKTEST,
        description="Run technical-only vs technical+sentiment under identical conditions.",
        allowed_callers=("backtest_agent",),
        input_schema="ComparisonCreateRequest",
        output_schema="ComparisonEnqueueResponse",
        has_side_effects=True,
        idempotent=False,
        timeout_seconds=900,
    ),
    # --- Risk role ---
    "run_risk_checks": ToolSpec(
        name="run_risk_checks",
        role=ToolRole.RISK,
        description="Read-only risk gate: drawdown, survivorship, look-ahead audit.",
        allowed_callers=("risk_agent",),
        input_schema="RiskChecksConfig",
        output_schema="RiskCheckReport",
        has_side_effects=False,
        idempotent=True,
        timeout_seconds=120,
    ),
    "cost_sensitivity_sweep": ToolSpec(
        name="cost_sensitivity_sweep",
        role=ToolRole.RISK,
        description="Pre/post-cost performance across cost bands (mandatory).",
        allowed_callers=("risk_agent",),
        input_schema="SensitivityRequest",
        output_schema="SensitivityResponse",
        has_side_effects=False,
        idempotent=True,
        timeout_seconds=600,
    ),
    # --- Report role ---
    "generate_memo": ToolSpec(
        name="generate_memo",
        role=ToolRole.REPORT,
        description="Assemble the research memo (summary + sections + limitations).",
        allowed_callers=("report_agent",),
        input_schema="ResearchPlan",
        output_schema="ResearchMemo",
        has_side_effects=True,
        idempotent=True,
        timeout_seconds=180,
    ),
}

#: All invocable tool names — the Orchestrator rejects anything outside this set.
KNOWN_TOOL_NAMES: frozenset[str] = frozenset(TOOL_CATALOG)


# ─── Run / step / tool-call schemas ──────────────────────────────────────────


class ToolCall(BaseModel):
    """One tool invocation within a step, with its own lifecycle.

    ``tool`` must be in :data:`KNOWN_TOOL_NAMES`; ``status`` follows
    :data:`STEP_TRANSITIONS`. ``input`` / ``output`` are opaque JSON snapshots
    for the audit log (FRA-85 persists them verbatim).
    """

    model_config = ConfigDict(extra="forbid")

    tool: str
    role: ToolRole
    status: AgentStepStatus = AgentStepStatus.QUEUED
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_tool_name(self) -> ToolCall:
        if self.tool not in KNOWN_TOOL_NAMES:
            raise ValueError(
                f"unknown tool {self.tool!r}; expected one of {sorted(KNOWN_TOOL_NAMES)}"
            )
        return self


class AgentStep(BaseModel):
    """One step of a run, owned by an agent role, holding >=0 tool calls."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    agent_role: str
    status: AgentStepStatus = AgentStepStatus.QUEUED
    tool_calls: list[ToolCall] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _validate_role(self) -> AgentStep:
        if self.agent_role not in AGENT_ROLES:
            raise ValueError(
                f"unknown agent_role {self.agent_role!r}; expected one of {sorted(AGENT_ROLES)}"
            )
        return self


class AgentRun(BaseModel):
    """A research run: a validated plan + ordered steps + aggregate status.

    The run's ``status`` follows :data:`RUN_TRANSITIONS`. This is the contract
    for the persistence layer (FRA-85) and the Orchestrator (FRA-86); it carries
    no execution logic here.
    """

    model_config = ConfigDict(extra="forbid")

    status: AgentRunStatus = AgentRunStatus.DRAFT
    plan: ResearchPlan
    steps: list[AgentStep] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error: str | None = None


__all__ = [
    "SCHEMA_VERSION",
    "AGENT_ROLES",
    "TECHNICAL_FACTOR_NAMES",
    "STRATEGY_NAMES",
    "VALIDATION_BASELINE_KINDS",
    "DEFAULT_COST_SENSITIVITY_BPS",
    "DataSource",
    "PriceField",
    "RebalanceFrequency",
    "PlanResolution",
    "FactorKind",
    "ToolRole",
    "AgentRunStatus",
    "AgentStepStatus",
    "TERMINAL_RUN_STATUSES",
    "RUN_TRANSITIONS",
    "STEP_TRANSITIONS",
    "IllegalStateTransitionError",
    "assert_run_transition",
    "assert_step_transition",
    "AssetRef",
    "FactorSpec",
    "SentimentProvenance",
    "StrategyConfig",
    "ValidationConfig",
    "RiskChecksConfig",
    "ResearchPlan",
    "ToolSpec",
    "TOOL_CATALOG",
    "KNOWN_TOOL_NAMES",
    "ToolCall",
    "AgentStep",
    "AgentRun",
]
