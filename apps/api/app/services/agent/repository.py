"""Repository for agent run / step / tool-call persistence (FRA-85).

The repository is the only layer that writes to ``research_runs`` /
``research_steps`` / ``agent_tool_calls``. It enforces three invariants:

1. **User ownership** — every read/write is scoped to ``user_id``. A run that
   belongs to another user is indistinguishable from one that does not exist
   (:class:`AgentRunNotFoundError` in both cases — HTTP 404 semantics, no leakage).

2. **State-machine integrity** — transitions are validated against the FRA-84
   allowlists (:func:`assert_run_transition` /
   :func:`assert_step_transition`) *before* the row is touched, so an illegal
   jump (e.g. ``succeeded → running``) never reaches the database. Terminal
   states are irreversible.

3. **Secret boundary** — every ``args`` / ``result`` payload is run through
   :func:`app.services.agent.sanitizer.sanitize` before flushing, so no API
   key, token, Authorization header, or raw traceback is ever persisted.

Side-effect tools (those with ``idempotency_key``) are deduplicated: a second
insert with the same ``(step_id, idempotency_key)`` raises
:class:`DuplicateToolCallError` *before* hitting the DB partial unique index.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import AgentToolCall, ResearchRun, ResearchStep
from app.schemas.agent import (
    SCHEMA_VERSION,
    AgentRunStatus,
    AgentStepStatus,
    assert_run_transition,
    assert_step_transition,
)
from app.services.agent.sanitizer import sanitize


class AgentRunNotFoundError(LookupError):
    """Raised when a run/step/tool-call is missing or not owned by the caller.

    The same exception covers *not found* and *owned by someone else* so the
    existence of another user's resource is never leaked (HTTP 404).
    """


class DuplicateToolCallError(ValueError):
    """Raised when a side-effect tool call repeats an idempotency key on a step."""


def compute_plan_hash(plan: dict[str, Any]) -> str:
    """SHA-256 of the canonical (sorted-key, compact) plan JSON.

    Two runs with the same plan produce the same hash, so drift / replay is
    detectable without diffing the full ``plan_json`` blob.
    """
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Run statuses that count as "started" for timestamp bookkeeping.
_RUN_ACTIVE: frozenset[AgentRunStatus] = frozenset({AgentRunStatus.QUEUED, AgentRunStatus.RUNNING})
# Step/tool-call statuses that are terminal.
_STEP_TERMINAL: frozenset[AgentStepStatus] = frozenset(
    {AgentStepStatus.SUCCEEDED, AgentStepStatus.FAILED, AgentStepStatus.CANCELED}
)


class AgentRunRepository:
    """User-scoped, state-machine-validated persistence for agent runs."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Runs ─────────────────────────────────────────────────────────────────

    def create_run(
        self,
        *,
        user_id: uuid.UUID,
        research_question: str,
        plan: dict[str, Any],
        plan_schema_version: str = SCHEMA_VERSION,
        planner_provider: str | None = None,
        planner_model: str | None = None,
        planner_prompt_version: str | None = None,
    ) -> ResearchRun:
        """Create a new run in ``draft`` status with a hashed plan snapshot."""
        run = ResearchRun(
            user_id=user_id,
            research_question=research_question,
            plan_schema_version=plan_schema_version,
            plan_json=plan,
            plan_hash=compute_plan_hash(plan),
            status=AgentRunStatus.DRAFT.value,
            planner_provider=planner_provider,
            planner_model=planner_model,
            planner_prompt_version=planner_prompt_version,
        )
        self._db.add(run)
        self._db.commit()
        self._db.refresh(run)
        return run

    def get_run(self, run_id: uuid.UUID, user_id: uuid.UUID) -> ResearchRun:
        """Fetch a run, scoped to *user_id*; raise :class:`AgentRunNotFoundError`."""
        run = self._db.scalar(
            select(ResearchRun).where(
                ResearchRun.id == run_id,
                ResearchRun.user_id == user_id,
            )
        )
        if run is None:
            raise AgentRunNotFoundError(f"research run {run_id} not found for user {user_id}")
        return run

    def list_runs(
        self,
        user_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ResearchRun]:
        """List a user's runs, newest first, optionally filtered by status."""
        stmt = select(ResearchRun).where(ResearchRun.user_id == user_id)
        if status is not None:
            stmt = stmt.where(ResearchRun.status == status)
        stmt = stmt.order_by(ResearchRun.created_at.desc()).limit(limit).offset(offset)
        return list(self._db.scalars(stmt))

    def transition_run(
        self,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        target: AgentRunStatus,
        *,
        error_summary: str | None = None,
        synthesis: dict[str, Any] | None = None,
        backtest_run_id: uuid.UUID | None = None,
    ) -> ResearchRun:
        """Atomically transition a run to *target* (validated against FRA-84).

        Timestamps are bookkept automatically: ``running`` stamps
        ``started_at``; a terminal status stamps ``completed_at`` /
        ``canceled_at``. ``synthesis`` is sanitized before persisting.
        """
        run = self.get_run(run_id, user_id)
        current = AgentRunStatus(run.status)
        assert_run_transition(current, target)

        now = datetime.now(UTC)
        run.status = target.value
        if target == AgentRunStatus.RUNNING and run.started_at is None:
            run.started_at = now
        if target == AgentRunStatus.SUCCEEDED:
            run.completed_at = now
        if target == AgentRunStatus.FAILED:
            run.completed_at = now
            if error_summary is not None:
                run.error_summary = error_summary
        if target == AgentRunStatus.CANCELED:
            run.canceled_at = now
        if synthesis is not None:
            run.synthesis_json = sanitize(synthesis)
        if backtest_run_id is not None:
            run.backtest_run_id = backtest_run_id

        self._db.commit()
        self._db.refresh(run)
        return run

    # ── Steps ────────────────────────────────────────────────────────────────

    def append_step(
        self,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        sequence: int,
        agent_role: str,
        kind: str,
        input_summary: dict[str, Any] | None = None,
    ) -> ResearchStep:
        """Append a ``queued`` step to a run (owned by *user_id*).

        ``(run_id, sequence)`` uniqueness is enforced by the DB; a duplicate
        raises :class:`sqlalchemy.exc.IntegrityError`.
        """
        # Ownership check (raises if not found / not owned).
        self.get_run(run_id, user_id)
        step = ResearchStep(
            run_id=run_id,
            sequence=sequence,
            agent_role=agent_role,
            kind=kind,
            status=AgentStepStatus.QUEUED.value,
            input_summary=sanitize(input_summary) if input_summary else None,
        )
        self._db.add(step)
        self._db.commit()
        self._db.refresh(step)
        return step

    def _get_step_owned(self, step_id: uuid.UUID, user_id: uuid.UUID) -> ResearchStep:
        """Fetch a step joined through its run to enforce ownership."""
        step = self._db.scalar(
            select(ResearchStep)
            .join(ResearchRun, ResearchStep.run_id == ResearchRun.id)
            .where(ResearchStep.id == step_id, ResearchRun.user_id == user_id)
        )
        if step is None:
            raise AgentRunNotFoundError(f"research step {step_id} not found for user {user_id}")
        return step

    def transition_step(
        self,
        step_id: uuid.UUID,
        user_id: uuid.UUID,
        target: AgentStepStatus,
        *,
        error: str | None = None,
        output_summary: dict[str, Any] | None = None,
    ) -> ResearchStep:
        """Atomically transition a step to *target* (validated against FRA-84)."""
        step = self._get_step_owned(step_id, user_id)
        current = AgentStepStatus(step.status)
        assert_step_transition(current, target)

        now = datetime.now(UTC)
        step.status = target.value
        if target == AgentStepStatus.RUNNING and step.started_at is None:
            step.started_at = now
        if target in _STEP_TERMINAL:
            step.finished_at = now
            if step.started_at is not None:
                delta = now - step.started_at
                step.duration_ms = int(delta.total_seconds() * 1000)
        if target == AgentStepStatus.FAILED and error is not None:
            step.error = error
        if output_summary is not None:
            step.output_summary = sanitize(output_summary)

        self._db.commit()
        self._db.refresh(step)
        return step

    def list_steps(self, run_id: uuid.UUID, user_id: uuid.UUID) -> list[ResearchStep]:
        """List a run's steps in sequence order (ownership-checked)."""
        self.get_run(run_id, user_id)  # raises if not owned
        return list(
            self._db.scalars(
                select(ResearchStep)
                .where(ResearchStep.run_id == run_id)
                .order_by(ResearchStep.sequence)
            )
        )

    # ── Tool calls ───────────────────────────────────────────────────────────

    def append_tool_call(
        self,
        step_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        tool_name: str,
        tool_version: str | None = None,
        args: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> AgentToolCall:
        """Record a ``queued`` tool invocation on a step.

        Side-effect tools pass ``idempotency_key``; a repeat on the same step
        raises :class:`DuplicateToolCallError` *before* the DB unique index.
        ``args`` is sanitized before persistence.
        """
        # Ownership check (step → run → user).
        self._get_step_owned(step_id, user_id)

        if idempotency_key is not None:
            existing = self._db.scalar(
                select(AgentToolCall).where(
                    AgentToolCall.step_id == step_id,
                    AgentToolCall.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                raise DuplicateToolCallError(
                    f"tool call {tool_name!r} with idempotency_key "
                    f"{idempotency_key!r} already recorded on step {step_id}"
                )

        call = AgentToolCall(
            step_id=step_id,
            tool_name=tool_name,
            tool_version=tool_version,
            status=AgentStepStatus.QUEUED.value,
            args_json=sanitize(args) if args else None,
            idempotency_key=idempotency_key,
        )
        self._db.add(call)
        self._db.commit()
        self._db.refresh(call)
        return call

    def _get_tool_call_owned(self, tool_call_id: uuid.UUID, user_id: uuid.UUID) -> AgentToolCall:
        """Fetch a tool call joined through step→run to enforce ownership."""
        call = self._db.scalar(
            select(AgentToolCall)
            .join(ResearchStep, AgentToolCall.step_id == ResearchStep.id)
            .join(ResearchRun, ResearchStep.run_id == ResearchRun.id)
            .where(AgentToolCall.id == tool_call_id, ResearchRun.user_id == user_id)
        )
        if call is None:
            raise AgentRunNotFoundError(
                f"agent tool call {tool_call_id} not found for user {user_id}"
            )
        return call

    def transition_tool_call(
        self,
        tool_call_id: uuid.UUID,
        user_id: uuid.UUID,
        target: AgentStepStatus,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        error_code: str | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
    ) -> AgentToolCall:
        """Atomically transition a tool call to *target* (validated vs FRA-84).

        ``result`` is sanitized before persistence.
        """
        call = self._get_tool_call_owned(tool_call_id, user_id)
        current = AgentStepStatus(call.status)
        assert_step_transition(current, target)

        now = datetime.now(UTC)
        call.status = target.value
        if target == AgentStepStatus.RUNNING and call.started_at is None:
            call.started_at = now
        if target in _STEP_TERMINAL:
            call.finished_at = now
            if call.started_at is not None:
                delta = now - call.started_at
                call.duration_ms = int(delta.total_seconds() * 1000)
        if target == AgentStepStatus.FAILED:
            if error is not None:
                call.error = error
            if error_code is not None:
                call.error_code = error_code
        if result is not None:
            call.result_json = sanitize(result)
        if evidence_refs is not None:
            call.evidence_refs = evidence_refs

        self._db.commit()
        self._db.refresh(call)
        return call

    def list_tool_calls(self, step_id: uuid.UUID, user_id: uuid.UUID) -> list[AgentToolCall]:
        """List a step's tool calls in creation order (ownership-checked)."""
        self._get_step_owned(step_id, user_id)  # raises if not owned
        return list(
            self._db.scalars(
                select(AgentToolCall)
                .where(AgentToolCall.step_id == step_id)
                .order_by(AgentToolCall.created_at)
            )
        )


__all__ = [
    "AgentRunNotFoundError",
    "AgentRunRepository",
    "DuplicateToolCallError",
    "compute_plan_hash",
]
