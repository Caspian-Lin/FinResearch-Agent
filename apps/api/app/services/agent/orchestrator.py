"""Agent Orchestrator — bounded two-phase execution loop (FRA-90).

The Orchestrator is the conductor that turns an approved ``ResearchPlan`` into a
completed ``ResearchSynthesis`` via a deterministic step sequence:

    data_agent → factor_agent → backtest_agent → risk_agent → report_agent

Every step, tool call, and state transition is persisted via
:class:`AgentRunRepository` so the audit trail is complete and the run can be
recovered after a worker crash.

Safety boundaries enforced here:
- **Plan-bound** — the LLM cannot invent tool names or change plan parameters;
  the step plan is generated *from* the approved plan.
- **Bounded** — max steps, per-run deadline, per-tool timeout, limited retries,
  repeated-call detection.
- **Idempotent** — side-effect tools carry idempotency keys; the orchestrator
  reuses completed tool calls on recovery instead of re-executing.
- **Ownable** — all persistence is scoped to ``user_id``.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent import AgentToolCall, ResearchRun, ResearchStep
from app.schemas.agent import (
    AgentRunStatus,
    AgentStepStatus,
    FactorKind,
    ResearchPlan,
)
from app.services.agent.report import synthesize
from app.services.agent.repository import (
    AgentRunRepository,
    DuplicateToolCallError,
)
from app.services.agent.risk import RiskEvidence, assess_risk
from app.services.agent.tools.protocol import ToolErrorKind, ToolResult
from app.services.agent.tools.registry import get_tool, validate_caller

logger = logging.getLogger(__name__)

#: Retriable tool error kinds.
_RETRIABLE: frozenset[ToolErrorKind] = frozenset(
    {ToolErrorKind.PROVIDER, ToolErrorKind.TIMEOUT, ToolErrorKind.INTERNAL}
)

#: Step statuses that count as terminal (no further action).
_STEP_TERMINAL: frozenset[AgentStepStatus] = frozenset(
    {AgentStepStatus.SUCCEEDED, AgentStepStatus.FAILED, AgentStepStatus.CANCELED}
)

#: Run statuses that are terminal.
_RUN_TERMINAL: frozenset[AgentRunStatus] = frozenset(
    {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED, AgentRunStatus.CANCELED}
)


# ─── Exceptions ──────────────────────────────────────────────────────────────


class OrchestratorError(Exception):
    """Base for controlled orchestrator errors (not a crash)."""


class RunCanceledError(OrchestratorError):
    """Run was canceled via the API while the orchestrator was executing."""


class RunDeadlineError(OrchestratorError):
    """Run exceeded ``agent_run_deadline_seconds``."""


class MaxStepsError(OrchestratorError):
    """Run exceeded ``agent_max_steps``."""


class CriticalToolError(OrchestratorError):
    """A critical (side-effect) tool failed and cannot be retried."""

    def __init__(self, tool_name: str, message: str) -> None:
        self.tool_name = tool_name
        self.message = message
        super().__init__(f"critical tool {tool_name!r} failed: {message}")


# ─── Planned tool call + step ────────────────────────────────────────────────


def _extract_run_id(ctx: dict[str, dict[str, Any] | None]) -> dict[str, Any] | None:
    """Extract run_id from a completed run_backtest result."""
    rb = ctx.get("run_backtest")
    if rb is not None and rb.get("run_id"):
        return {"run_id": rb["run_id"]}
    return None


@dataclass(frozen=True)
class PlannedToolCall:
    """A tool call generated from the plan (pre-execution).

    ``build_args`` receives a context dict of earlier tool *result data* within
    the same step (keyed by tool_name) and returns the args for this call.
    Returning ``None`` skips this call — used when an earlier dependency failed.
    """

    tool_name: str
    build_args: Callable[[dict[str, dict[str, Any] | None]], dict[str, Any] | None]
    idempotency_key: str | None = None
    critical: bool = False


@dataclass(frozen=True)
class PlannedStep:
    """One step in the deterministic execution plan."""

    sequence: int
    agent_role: str
    kind: str
    input_summary: dict[str, Any]
    tool_calls: list[PlannedToolCall] = field(default_factory=list)


# ─── Step plan generation ────────────────────────────────────────────────────


def generate_step_plan(plan: ResearchPlan, user_id: uuid.UUID) -> list[PlannedStep]:
    """Produce a deterministic step list from an approved plan.

    The LLM never controls step order or tool selection — this function is the
    sole source of truth for what gets executed.
    """
    asset_ids = [str(ref.asset_id) for ref in plan.universe if ref.asset_id is not None]
    all_symbols = [ref.symbol for ref in plan.universe] + [plan.benchmark.symbol]

    start_str = plan.start_date.strftime("%Y-%m-%d")
    end_str = plan.end_date.strftime("%Y-%m-%d")
    source = plan.data_source.value
    price_field = plan.price_field.value

    tech_factors = [f.name for f in plan.factors if f.kind == FactorKind.TECHNICAL]

    steps: list[PlannedStep] = []
    seq = 0

    # ── Step 1: data_agent — verify resolution + check coverage ──────────
    seq += 1
    steps.append(
        PlannedStep(
            sequence=seq,
            agent_role="data_agent",
            kind="data:resolve_and_coverage",
            input_summary={
                "symbols": all_symbols,
                "window": {"start": start_str, "end": end_str},
                "source": source,
            },
            tool_calls=[
                PlannedToolCall(
                    tool_name="resolve_assets",
                    build_args=lambda _ctx: {"symbols": all_symbols},
                ),
                PlannedToolCall(
                    tool_name="check_coverage",
                    build_args=lambda _ctx: {
                        "asset_ids": asset_ids,
                        "start": start_str,
                        "end": end_str,
                        "source": source,
                    },
                ),
            ],
        )
    )

    # ── Step 2: factor_agent — compute + evaluate (only technical) ───────
    if tech_factors:
        seq += 1
        tcalls: list[PlannedToolCall] = [
            PlannedToolCall(
                tool_name="compute_factor",
                build_args=lambda _ctx: {
                    "asset_ids": asset_ids,
                    "factor_names": tech_factors,
                    "start": start_str,
                    "end": end_str,
                    "source": source,
                    "price_field": price_field,
                },
                idempotency_key=f"compute_factor:{'+'.join(sorted(tech_factors))}",
                critical=True,
            ),
        ]
        for fname in tech_factors:
            _fn = fname  # capture

            def _build_eval(ctx: dict[str, Any], _fn: str = _fn) -> dict[str, Any] | None:
                if ctx.get("compute_factor") is None:
                    return None
                return {
                    "asset_ids": asset_ids,
                    "factor_name": _fn,
                    "start": start_str,
                    "end": end_str,
                    "source": source,
                    "horizon": 21,
                    "price_field": price_field,
                }

            tcalls.append(
                PlannedToolCall(
                    tool_name="evaluate_factor",
                    build_args=_build_eval,
                )
            )
        steps.append(
            PlannedStep(
                sequence=seq,
                agent_role="factor_agent",
                kind="factor:compute_and_evaluate",
                input_summary={"factors": tech_factors, "universe_size": len(asset_ids)},
                tool_calls=tcalls,
            )
        )

    # ── Step 3: backtest_agent — run + read ──────────────────────────────
    seq += 1
    benchmark_id = plan.benchmark.asset_id
    steps.append(
        PlannedStep(
            sequence=seq,
            agent_role="backtest_agent",
            kind="backtest:run_and_read",
            input_summary={
                "strategy": plan.strategy.name,
                "window": {"start": start_str, "end": end_str},
                "cost_bps": plan.transaction_cost_bps,
            },
            tool_calls=[
                PlannedToolCall(
                    tool_name="run_backtest",
                    build_args=lambda _ctx: {
                        "universe": asset_ids,
                        "strategy_name": plan.strategy.name,
                        "start": start_str,
                        "end": end_str,
                        "strategy_params": plan.strategy.params,
                        "cost_bps": plan.transaction_cost_bps,
                        "rebalance": plan.strategy.rebalance.value,
                        "price_field": price_field,
                        "benchmark_asset_id": str(benchmark_id) if benchmark_id else None,
                        "user_id": str(user_id),
                    },
                    idempotency_key="run_backtest",
                    critical=True,
                ),
                PlannedToolCall(
                    tool_name="read_backtest",
                    build_args=lambda ctx: _extract_run_id(ctx),
                    critical=True,
                ),
            ],
        )
    )

    # ── Step 4: risk_agent — deterministic assess (no tools) ─────────────
    seq += 1
    steps.append(
        PlannedStep(
            sequence=seq,
            agent_role="risk_agent",
            kind="risk:assess",
            input_summary={},
            tool_calls=[],
        )
    )

    # ── Step 5: report_agent — synthesize (no tools) ─────────────────────
    seq += 1
    steps.append(
        PlannedStep(
            sequence=seq,
            agent_role="report_agent",
            kind="report:synthesize",
            input_summary={},
            tool_calls=[],
        )
    )

    return steps


# ─── Bounded execution helpers ───────────────────────────────────────────────


def _is_run_canceled(db: Session, run_id: uuid.UUID) -> bool:
    """Check the DB for a committed cancellation (bypassing ORM identity map)."""
    raw = db.execute(
        select(ResearchRun.status).where(ResearchRun.id == run_id)
    ).scalar_one_or_none()
    return raw == AgentRunStatus.CANCELED.value


def _check_deadline(started_at: datetime) -> None:
    """Abort if the wall-clock deadline has passed."""
    deadline = started_at + timedelta(seconds=settings.agent_run_deadline_seconds)
    if datetime.now(UTC) > deadline:
        raise RunDeadlineError(f"run exceeded deadline of {settings.agent_run_deadline_seconds}s")


def _execute_tool_with_retry(
    tool_name: str,
    args: dict[str, Any],
    *,
    db: Session,
) -> ToolResult:
    """Execute a tool, retrying retriable errors up to ``agent_max_retries``."""
    retries = settings.agent_max_retries
    tool = get_tool(tool_name)
    last_result: ToolResult | None = None

    for attempt in range(1 + retries):
        if attempt > 0:
            backoff = min(0.5 * (2 ** (attempt - 1)), 10.0)
            logger.info("retrying %s (attempt %d) after %.1fs", tool_name, attempt, backoff)
            time.sleep(backoff)

        result = tool.execute(args, db=db)
        if result.success:
            return result

        last_result = result
        if result.error and result.error.retriable and attempt < retries:
            continue
        return result

    assert last_result is not None
    return last_result


# ─── Recovery helpers ────────────────────────────────────────────────────────


def _find_step_by_sequence(db: Session, run_id: uuid.UUID, sequence: int) -> ResearchStep | None:
    """Return an existing step for this run + sequence (recovery lookup)."""
    return db.scalar(
        select(ResearchStep).where(
            ResearchStep.run_id == run_id,
            ResearchStep.sequence == sequence,
        )
    )


def _find_existing_tool_call(
    db: Session, step_id: uuid.UUID, idempotency_key: str | None
) -> AgentToolCall | None:
    """Return an existing tool call on this step with the same idempotency key."""
    if idempotency_key is None:
        return None
    return db.scalar(
        select(AgentToolCall).where(
            AgentToolCall.step_id == step_id,
            AgentToolCall.idempotency_key == idempotency_key,
        )
    )


# ─── Step execution ──────────────────────────────────────────────────────────


def _execute_planned_step(
    repo: AgentRunRepository,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    step_spec: PlannedStep,
    *,
    db: Session,
    started_at: datetime,
    call_counts: dict[str, int],
) -> dict[str, dict[str, Any] | None]:
    """Execute one planned step's tool calls sequentially.

    Returns ``{tool_name: result_data_or_None}``.
    """
    # ── Create or reuse step ─────────────────────────────────────────────
    existing_step = _find_step_by_sequence(db, run_id, step_spec.sequence)
    if existing_step is not None:
        step = existing_step
        if AgentStepStatus(step.status) in _STEP_TERMINAL:
            logger.info(
                "step %d (%s) already terminal — skipping",
                step_spec.sequence,
                step_spec.kind,
            )
            results: dict[str, dict[str, Any] | None] = {}
            for tc in repo.list_tool_calls(step.id, user_id):
                if AgentStepStatus(tc.status) == AgentStepStatus.SUCCEEDED and tc.result_json:
                    results[tc.tool_name] = tc.result_json
                else:
                    results[tc.tool_name] = None
            return results
        if AgentStepStatus(step.status) == AgentStepStatus.QUEUED:
            repo.transition_step(step.id, user_id, AgentStepStatus.RUNNING)
    else:
        step = repo.append_step(
            run_id,
            user_id,
            sequence=step_spec.sequence,
            agent_role=step_spec.agent_role,
            kind=step_spec.kind,
            input_summary=step_spec.input_summary,
        )
        repo.transition_step(step.id, user_id, AgentStepStatus.RUNNING)

    # ── Execute tool calls ───────────────────────────────────────────────
    ctx: dict[str, dict[str, Any] | None] = {}
    step_errors: list[str] = []

    for tc_spec in step_spec.tool_calls:
        _check_deadline(started_at)
        if _is_run_canceled(db, run_id):
            repo.transition_step(step.id, user_id, AgentStepStatus.CANCELED)
            raise RunCanceledError()

        # Build args (may return None to skip).
        args = tc_spec.build_args(ctx)
        if not args:
            ctx[tc_spec.tool_name] = None
            continue

        # Repeated-call guard.
        call_counts[tc_spec.tool_name] = call_counts.get(tc_spec.tool_name, 0) + 1
        if call_counts[tc_spec.tool_name] > 1 + settings.agent_max_retries:
            msg = (
                f"tool {tc_spec.tool_name!r} called {call_counts[tc_spec.tool_name]} "
                f"times — possible loop"
            )
            step_errors.append(msg)
            if tc_spec.critical:
                repo.transition_step(step.id, user_id, AgentStepStatus.FAILED, error=msg)
                raise CriticalToolError(tc_spec.tool_name, msg)
            ctx[tc_spec.tool_name] = None
            continue

        validate_caller(tc_spec.tool_name, step_spec.agent_role)

        # Recovery: check existing tool call.
        existing_tc = _find_existing_tool_call(db, step.id, tc_spec.idempotency_key)
        if existing_tc is not None:
            tc_status = AgentStepStatus(existing_tc.status)
            if tc_status in _STEP_TERMINAL:
                logger.info(
                    "tool %s on step %d already %s — reusing",
                    tc_spec.tool_name,
                    step_spec.sequence,
                    tc_status.value,
                )
                ctx[tc_spec.tool_name] = (
                    existing_tc.result_json if tc_status == AgentStepStatus.SUCCEEDED else None
                )
                continue
            repo.transition_tool_call(existing_tc.id, user_id, AgentStepStatus.CANCELED)

        # Create + execute.
        try:
            tc = repo.append_tool_call(
                step.id,
                user_id,
                tool_name=tc_spec.tool_name,
                args=args,
                idempotency_key=tc_spec.idempotency_key,
            )
        except DuplicateToolCallError:
            existing_tc = _find_existing_tool_call(db, step.id, tc_spec.idempotency_key)
            assert existing_tc is not None
            tc = existing_tc
            if AgentStepStatus(tc.status) in _STEP_TERMINAL:
                ctx[tc_spec.tool_name] = (
                    tc.result_json
                    if AgentStepStatus(tc.status) == AgentStepStatus.SUCCEEDED
                    else None
                )
                continue

        repo.transition_tool_call(tc.id, user_id, AgentStepStatus.RUNNING)

        result = _execute_tool_with_retry(tc_spec.tool_name, args, db=db)

        ev_refs: list[dict[str, Any]] | None = None
        if result.side_effect_ref:
            ev_refs = [{"ref": result.side_effect_ref}]

        repo.transition_tool_call(
            tc.id,
            user_id,
            AgentStepStatus.SUCCEEDED if result.success else AgentStepStatus.FAILED,
            result=result.data,
            error=result.error.message if result.error else None,
            error_code=result.error.kind.value if result.error else None,
            evidence_refs=ev_refs,
        )

        ctx[tc_spec.tool_name] = result.data if result.success else None

        if not result.success and result.error:
            err_msg = f"{tc_spec.tool_name}: {result.error.kind.value} — {result.error.message}"
            step_errors.append(err_msg)
            if tc_spec.critical:
                repo.transition_step(step.id, user_id, AgentStepStatus.FAILED, error=err_msg)
                raise CriticalToolError(tc_spec.tool_name, err_msg)

    # ── Step complete ────────────────────────────────────────────────────
    repo.transition_step(
        step.id,
        user_id,
        AgentStepStatus.FAILED
        if step_errors and not any(ctx.values())
        else AgentStepStatus.SUCCEEDED,
        output_summary={"tools_executed": list(ctx.keys()), "errors": step_errors},
    )
    return ctx


def _execute_no_tool_step(
    repo: AgentRunRepository,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    step_spec: PlannedStep,
    input_summary: dict[str, Any],
    output_summary: dict[str, Any],
    *,
    db: Session,
) -> None:
    """Record a non-tool step (risk_agent / report_agent)."""
    existing = _find_step_by_sequence(db, run_id, step_spec.sequence)
    if existing is not None and AgentStepStatus(existing.status) in _STEP_TERMINAL:
        return
    step = existing or repo.append_step(
        run_id,
        user_id,
        sequence=step_spec.sequence,
        agent_role=step_spec.agent_role,
        kind=step_spec.kind,
        input_summary=input_summary,
    )
    if AgentStepStatus(step.status) != AgentStepStatus.RUNNING:
        repo.transition_step(step.id, user_id, AgentStepStatus.RUNNING)
    repo.transition_step(
        step.id,
        user_id,
        AgentStepStatus.SUCCEEDED,
        output_summary=output_summary,
    )


# ─── Main orchestrator entry point ───────────────────────────────────────────


def run_research(run_id: uuid.UUID, user_id: uuid.UUID, *, db: Session) -> str:
    """Execute a research run to completion or failure.

    Returns the final run status string (``succeeded`` / ``failed`` /
    ``canceled``). All state transitions are persisted.
    """
    repo = AgentRunRepository(db)
    run = repo.get_run(run_id, user_id)
    plan = ResearchPlan.model_validate(run.plan_json)

    # Guard: already terminal.
    current = AgentRunStatus(run.status)
    if current in _RUN_TERMINAL:
        return run.status

    # Transition to RUNNING (or resume).
    if current == AgentRunStatus.RUNNING:
        started_at = run.started_at or datetime.now(UTC)
    else:
        run = repo.transition_run(run_id, user_id, AgentRunStatus.RUNNING)
        started_at = run.started_at or datetime.now(UTC)

    step_plan = generate_step_plan(plan, user_id)
    call_counts: dict[str, int] = {}
    evidence = RiskEvidence()
    backtest_run_id: uuid.UUID | None = None
    synthesis_dict: dict[str, Any] | None = None

    try:
        for step_spec in step_plan:
            if _is_run_canceled(db, run_id):
                raise RunCanceledError()
            _check_deadline(started_at)

            if step_spec.sequence > settings.agent_max_steps:
                raise MaxStepsError(
                    f"step {step_spec.sequence} exceeds max_steps={settings.agent_max_steps}"
                )

            # ── Risk / report phases (no tools) ───────────────────────────
            if step_spec.agent_role == "risk_agent":
                _execute_no_tool_step(
                    repo,
                    run_id,
                    user_id,
                    step_spec,
                    input_summary={"tool_errors": list(evidence.tool_errors)},
                    output_summary={"overall_status": "(pending)"},
                    db=db,
                )
                continue

            if step_spec.agent_role == "report_agent":
                assessment = assess_risk(plan, evidence)
                synthesis = synthesize(plan, evidence, assessment)
                synthesis_dict = dataclasses.asdict(synthesis)
                _execute_no_tool_step(
                    repo,
                    run_id,
                    user_id,
                    step_spec,
                    input_summary={
                        "overall_status": assessment.overall_status.value,
                        "restricted": synthesis.restricted,
                    },
                    output_summary={
                        "restricted": synthesis.restricted,
                        "observations": len(synthesis.key_observations),
                        "limitations": len(synthesis.limitations),
                    },
                    db=db,
                )
                continue

            # ── Tool-based step ───────────────────────────────────────────
            ctx = _execute_planned_step(
                repo,
                run_id,
                user_id,
                step_spec,
                db=db,
                started_at=started_at,
                call_counts=call_counts,
            )

            # ── Extract evidence ──────────────────────────────────────────
            if step_spec.agent_role == "data_agent":
                coverage = ctx.get("check_coverage")
                if coverage:
                    evidence.coverage = coverage

            elif step_spec.agent_role == "factor_agent":
                eval_data = ctx.get("evaluate_factor")
                if eval_data:
                    evidence.factor_evaluation = eval_data

            elif step_spec.agent_role == "backtest_agent":
                rb_data = ctx.get("read_backtest")
                if rb_data:
                    evidence.backtest_result = rb_data
                run_bt = ctx.get("run_backtest")
                if run_bt and run_bt.get("run_id"):
                    with contextlib.suppress(ValueError, TypeError):
                        backtest_run_id = uuid.UUID(str(run_bt["run_id"]))
                for tc_name in ("run_backtest", "read_backtest"):
                    if ctx.get(tc_name) is None:
                        evidence.tool_errors.append(f"{tc_name} returned no data")

        # ── Final risk assessment for output_summary update ───────────────
        assessment = assess_risk(plan, evidence)

        # Update risk step output if it was recorded with placeholder.
        risk_step = _find_step_by_sequence(db, run_id, step_plan[-2].sequence)
        if risk_step is not None and AgentStepStatus(risk_step.status) == AgentStepStatus.SUCCEEDED:
            risk_step.output_summary = {
                "overall_status": assessment.overall_status.value,
                "finding_count": assessment.finding_count,
                "failed_rules": assessment.failed_rules,
            }
            db.commit()

        # ── SUCCEEDED ─────────────────────────────────────────────────────
        _safe_transition(
            repo,
            run_id,
            user_id,
            AgentRunStatus.SUCCEEDED,
            synthesis=synthesis_dict,
            backtest_run_id=backtest_run_id,
        )
        return AgentRunStatus.SUCCEEDED.value

    except RunCanceledError:
        _safe_transition(repo, run_id, user_id, AgentRunStatus.CANCELED)
        return AgentRunStatus.CANCELED.value

    except (RunDeadlineError, MaxStepsError) as exc:
        _safe_transition(
            repo,
            run_id,
            user_id,
            AgentRunStatus.FAILED,
            error_summary=f"{type(exc).__name__}: {exc}",
        )
        return AgentRunStatus.FAILED.value

    except CriticalToolError as exc:
        _safe_transition(
            repo,
            run_id,
            user_id,
            AgentRunStatus.FAILED,
            error_summary=f"critical tool failed: {exc.tool_name}: {exc.message}",
        )
        return AgentRunStatus.FAILED.value


def _safe_transition(
    repo: AgentRunRepository,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    target: AgentRunStatus,
    *,
    error_summary: str | None = None,
    synthesis: dict[str, Any] | None = None,
    backtest_run_id: uuid.UUID | None = None,
) -> None:
    """Best-effort state transition; logs if it fails."""
    try:
        repo.transition_run(
            run_id,
            user_id,
            target,
            error_summary=error_summary,
            synthesis=synthesis,
            backtest_run_id=backtest_run_id,
        )
    except Exception:
        logger.exception("failed to transition run %s to %s", run_id, target.value)


__all__ = [
    "CriticalToolError",
    "MaxStepsError",
    "OrchestratorError",
    "PlannedStep",
    "PlannedToolCall",
    "RunCanceledError",
    "RunDeadlineError",
    "generate_step_plan",
    "run_research",
]
