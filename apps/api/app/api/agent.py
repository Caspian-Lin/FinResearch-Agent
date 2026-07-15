"""Agent API — two-phase plan/run lifecycle, trace, and cancel (FRA-90).

Endpoints
---------
- ``POST /agent/plans``               NL hypothesis → plan draft (no side effects)
- ``POST /agent/runs``                Submit approved plan + hash → create + enqueue (202)
- ``GET  /agent/runs``                Caller's runs, paginated
- ``GET  /agent/runs/{run_id}``       Run detail (status, plan, synthesis, progress)
- ``GET  /agent/runs/{run_id}/trace`` Ordered steps + nested tool calls
- ``POST /agent/runs/{run_id}/cancel`` Idempotent cancel

Ownership: every read/write is scoped to ``current_user.id``. A run owned by
another user is indistinguishable from a missing one (HTTP 404, no leak).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from rq import Queue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models.agent import ResearchRun, ResearchStep
from app.models.user import User
from app.schemas.agent import (
    TERMINAL_RUN_STATUSES,
    AgentRunStatus,
    AgentStepStatus,
    ResearchPlan,
)
from app.schemas.agent_run import (
    AgentCancelResponse,
    AgentPlanRequest,
    AgentPlanResponse,
    AgentRunCreateRequest,
    AgentRunDetail,
    AgentRunEnqueuedResponse,
    AgentRunListResponse,
    AgentRunSummary,
    AgentTraceResponse,
    StepTrace,
    ToolCallTrace,
)
from app.services.agent.planner import DbAssetResolver, get_planner
from app.services.agent.repository import (
    AgentRunNotFoundError,
    AgentRunRepository,
    compute_plan_hash,
)
from app.services.llm_config import resolve_llm_config
from app.services.sync import get_agent_queue

router = APIRouter(prefix="/agent", tags=["agent"])

DBSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AgentQueue = Annotated[Queue, Depends(get_agent_queue)]

AGENT_JOB_TIMEOUT = 900
AGENT_RESULT_TTL = 86400
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


# ─── POST /agent/plans ───────────────────────────────────────────────────────


@router.post(
    "/plans",
    response_model=AgentPlanResponse,
    summary="Create a research plan draft from a natural-language hypothesis",
)
def create_plan(
    payload: AgentPlanRequest,
    db: DBSession,
    current_user: CurrentUser,
) -> AgentPlanResponse:
    """Turn a hypothesis into a validated ``ResearchPlan`` (no side effects).

    The planner resolves symbols to asset IDs via the DB. If the hypothesis is
    ambiguous or the planner output fails contract validation, the response
    carries ``clarification_needed`` / ``validation_errors`` instead of a plan.
    No run is created — the caller submits the returned plan + ``plan_hash`` to
    ``POST /agent/runs`` to approve and enqueue.
    """
    planner = get_planner(llm_config=resolve_llm_config(current_user.id, db))
    resolver = DbAssetResolver(db)
    result = planner.plan(payload.hypothesis, resolver=resolver)

    if not result.ok:
        return AgentPlanResponse(
            research_question=payload.hypothesis.strip(),
            clarification_needed=result.clarification_needed,
            validation_errors=result.validation_errors,
            planner_provider=planner.name,
            planner_model=None,
        )

    assert result.plan is not None
    plan = result.plan
    plan_hash = compute_plan_hash(plan.model_dump(mode="json"))

    prov = result.provenance
    return AgentPlanResponse(
        research_question=plan.research_question,
        plan=plan,
        plan_hash=plan_hash,
        planner_provider=prov.provider if prov else planner.name,
        planner_model=prov.model if prov else None,
    )


# ─── POST /agent/runs ────────────────────────────────────────────────────────


@router.post(
    "/runs",
    response_model=AgentRunEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an approved plan and enqueue a research run",
)
def create_run(
    payload: AgentRunCreateRequest,
    db: DBSession,
    current_user: CurrentUser,
    queue: AgentQueue,
) -> AgentRunEnqueuedResponse:
    """Validate the plan hash, create a run, transition to ``queued``, enqueue.

    The ``plan_hash`` must match a SHA-256 of the canonical plan JSON — this
    ensures the user is approving the exact plan they reviewed.
    """
    # Verify hash integrity.
    actual_hash = compute_plan_hash(payload.plan.model_dump(mode="json"))
    if actual_hash != payload.plan_hash:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="plan_hash does not match the submitted plan; the plan may have been modified",
        )

    repo = AgentRunRepository(db)
    run = repo.create_run(
        user_id=current_user.id,
        research_question=payload.plan.research_question,
        plan=payload.plan.model_dump(mode="json"),
        planner_provider=None,
    )

    # Transition draft → validated → queued.
    run = repo.transition_run(run.id, current_user.id, AgentRunStatus.VALIDATED)
    run = repo.transition_run(run.id, current_user.id, AgentRunStatus.QUEUED)

    # Enqueue the worker job.
    queue.enqueue(
        "worker.tasks.agent.run_research_job",
        str(run.id),
        job_timeout=AGENT_JOB_TIMEOUT,
        result_ttl=AGENT_RESULT_TTL,
    )

    return AgentRunEnqueuedResponse(
        run_id=run.id,
        status=run.status,
        plan_hash=run.plan_hash,
    )


# ─── GET /agent/runs ─────────────────────────────────────────────────────────


@router.get(
    "/runs",
    response_model=AgentRunListResponse,
    summary="List the caller's research runs",
)
def list_runs(
    db: DBSession,
    current_user: CurrentUser,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> AgentRunListResponse:
    """Return the caller's runs, newest first."""
    repo = AgentRunRepository(db)
    runs = repo.list_runs(current_user.id, status=status_filter, limit=limit, offset=offset)

    total = (
        db.scalar(
            select(func.count())
            .select_from(ResearchRun)
            .where(ResearchRun.user_id == current_user.id)
        )
        or 0
    )

    summaries = [_to_summary(r, db, current_user.id) for r in runs]
    return AgentRunListResponse(runs=summaries, total=total, limit=limit, offset=offset)


# ─── GET /agent/runs/{run_id} ────────────────────────────────────────────────


@router.get(
    "/runs/{run_id}",
    response_model=AgentRunDetail,
    summary="Get a run's detail (status, plan, synthesis, progress)",
)
def get_run(
    run_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
) -> AgentRunDetail:
    """Return full detail for a run owned by the caller."""
    repo = AgentRunRepository(db)
    try:
        run = repo.get_run(run_id, current_user.id)
    except AgentRunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found") from None

    steps = repo.list_steps(run_id, current_user.id)
    completed = sum(1 for s in steps if AgentStepStatus(s.status) in _STEP_TERMINAL_STATUSES)

    plan_obj: ResearchPlan | None = None
    if run.plan_json:
        try:
            plan_obj = ResearchPlan.model_validate(run.plan_json)
        except Exception:
            plan_obj = None

    summary = _to_summary(run, db, current_user.id)
    return AgentRunDetail(
        **summary.model_dump(),
        plan=plan_obj,
        synthesis=run.synthesis_json,
        step_count=len(steps),
        completed_steps=completed,
    )


# ─── GET /agent/runs/{run_id}/trace ──────────────────────────────────────────


@router.get(
    "/runs/{run_id}/trace",
    response_model=AgentTraceResponse,
    summary="Get the ordered step + tool-call trace for a run",
)
def get_trace(
    run_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
) -> AgentTraceResponse:
    """Return the full execution trace, sanitized (no secrets, no tracebacks)."""
    repo = AgentRunRepository(db)
    try:
        run = repo.get_run(run_id, current_user.id)
    except AgentRunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found") from None

    steps = repo.list_steps(run_id, current_user.id)
    step_traces: list[StepTrace] = []
    for s in steps:
        tool_calls = repo.list_tool_calls(s.id, current_user.id)
        tc_traces = [
            ToolCallTrace(
                id=tc.id,
                tool_name=tc.tool_name,
                status=tc.status,
                args=tc.args_json,
                result=tc.result_json,
                error=tc.error,
                error_code=tc.error_code,
                evidence_refs=tc.evidence_refs,
                duration_ms=tc.duration_ms,
                started_at=tc.started_at,
                finished_at=tc.finished_at,
            )
            for tc in tool_calls
        ]
        step_traces.append(
            StepTrace(
                id=s.id,
                sequence=s.sequence,
                agent_role=s.agent_role,
                kind=s.kind,
                status=s.status,
                input_summary=s.input_summary,
                output_summary=s.output_summary,
                error=s.error,
                duration_ms=s.duration_ms,
                started_at=s.started_at,
                finished_at=s.finished_at,
                tool_calls=tc_traces,
            )
        )

    return AgentTraceResponse(run_id=run_id, run_status=run.status, steps=step_traces)


# ─── POST /agent/runs/{run_id}/cancel ────────────────────────────────────────


@router.post(
    "/runs/{run_id}/cancel",
    response_model=AgentCancelResponse,
    summary="Cancel a queued or running run (idempotent)",
)
def cancel_run(
    run_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
) -> AgentCancelResponse:
    """Idempotent cancel. Terminal runs are returned as-is (no error)."""
    repo = AgentRunRepository(db)
    try:
        run = repo.get_run(run_id, current_user.id)
    except AgentRunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found") from None

    current = AgentRunStatus(run.status)
    if current in TERMINAL_RUN_STATUSES:
        return AgentCancelResponse(
            run_id=run_id,
            status=run.status,
            message=f"run is already in terminal status '{run.status}'",
        )

    # Transition to canceled (works from queued, running, draft, validated).
    repo.transition_run(run_id, current_user.id, AgentRunStatus.CANCELED)
    return AgentCancelResponse(
        run_id=run_id,
        status=AgentRunStatus.CANCELED.value,
        message="run canceled",
    )


# ─── Helpers ─────────────────────────────────────────────────────────────────

_STEP_TERMINAL_STATUSES: frozenset[AgentStepStatus] = frozenset(
    {AgentStepStatus.SUCCEEDED, AgentStepStatus.FAILED, AgentStepStatus.CANCELED}
)


def _to_summary(run: ResearchRun, db: Session, user_id: uuid.UUID) -> AgentRunSummary:
    """Build a compact summary, including current-step progress."""
    # Find the latest non-terminal step for progress display.
    current_step: str | None = None
    steps = db.scalars(
        select(ResearchStep)
        .where(ResearchStep.run_id == run.id)
        .order_by(ResearchStep.sequence.desc())
        .limit(1)
    ).all()
    if steps:
        current_step = steps[0].agent_role

    return AgentRunSummary(
        id=run.id,
        research_question=run.research_question or "",
        status=run.status,
        plan_hash=run.plan_hash or "",
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error_summary=run.error_summary,
        current_step=current_step,
    )
