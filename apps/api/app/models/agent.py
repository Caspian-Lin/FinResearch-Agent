"""Agent run / step / tool-call persistence ORM models (FRA-85).

Three tables give the Week 5 research agent an auditable, recoverable run log
that stitches together the natural-language question, the approved plan, each
agent-role step, every tool invocation, and the downstream experiment ids:

* ``research_runs``   — one row per research run: the original question, the
  versioned plan (JSON + hash), the run lifecycle, planner provenance, the
  final synthesis, and an auditable link to downstream experiments.
* ``research_steps``  — ordered steps within a run, each owned by an agent
  role. ``(run_id, sequence)`` is unique so a run has a linear, gap-free audit
  trail.
* ``agent_tool_calls``— individual tool invocations within a step. Side-effect
  tools carry an ``idempotency_key``; a partial unique index prevents the same
  side-effect from executing twice on the same step.

Status values mirror the FRA-84 state machine
(:data:`app.schemas.agent.AgentRunStatus` /
:data:`app.schemas.agent.AgentStepStatus`). They are enforced both at the
application layer (``assert_run_transition`` / ``assert_step_transition`` in
the repository) and at the database layer (``CHECK`` constraints in the
migration — defense in depth).

Sensitive data is **never** persisted: the repository runs every
``args_json`` / ``result_json`` through :mod:`app.services.agent.sanitizer`
before flushing, so API keys, ``Authorization`` headers, and raw tracebacks
are stripped at the boundary.

See ``docs/database-schema.md`` for the table diagrams and ``docs/agent-design.md``
for the state-machine + tool-catalog contract.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Allowed values for ``ResearchRun.status`` — mirrors
#: :class:`app.schemas.agent.AgentRunStatus` (terminal = succeeded/failed/canceled).
RESEARCH_RUN_STATUSES: tuple[str, ...] = (
    "draft",
    "validated",
    "queued",
    "running",
    "succeeded",
    "failed",
    "canceled",
)

#: Allowed values for ``ResearchStep.status`` / ``AgentToolCall.status`` — mirrors
#: :class:`app.schemas.agent.AgentStepStatus` (no draft/validated phase; steps
#: only exist once a run is queued).
STEP_STATUSES: tuple[str, ...] = ("queued", "running", "succeeded", "failed", "canceled")

#: Allowed values for ``ResearchStep.agent_role`` — mirrors
#: :data:`app.schemas.agent.AGENT_ROLES`.
STEP_AGENT_ROLES: tuple[str, ...] = (
    "research_planner",
    "data_agent",
    "factor_agent",
    "backtest_agent",
    "risk_agent",
    "report_agent",
)


class ResearchRun(Base):
    """One research run: a user's question, the approved plan, and its lifecycle.

    ``plan_json`` stores the full :class:`app.schemas.agent.ResearchPlan` (which
    is itself versioned via ``plan_schema_version``); ``plan_hash`` is the SHA-256
    of the canonical JSON so a diff / replay can detect whether the plan changed
    between runs. ``status`` follows the FRA-84 run state machine. The optional
    ``backtest_run_id`` links the run to its primary downstream backtest for
    reproducibility audit (ON DELETE SET NULL — deleting a backtest must not
    erase the research trail, only break the link).
    """

    __tablename__ = "research_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    research_question: Mapped[str] = mapped_column(Text, nullable=False)
    # Version of the ResearchPlan contract (FRA-84 ``SCHEMA_VERSION``); lets a
    # future reader reject / migrate plans emitted by an older schema.
    plan_schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    # Full ResearchPlan snapshot (JSONB) — the auditable, replayable plan.
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # SHA-256 hex of the canonical plan JSON — detects plan drift between runs.
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # FRA-84 run lifecycle: draft → validated → queued → running → terminal.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )

    # Planner provenance (which LLM produced / validated the plan).
    planner_provider: Mapped[str | None] = mapped_column(String(64))
    planner_model: Mapped[str | None] = mapped_column(String(128))
    planner_prompt_version: Mapped[str | None] = mapped_column(String(64))

    # Final synthesis (the Report Agent's structured output), nullable until done.
    synthesis_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Human-readable error summary on failure (≤ 2000 chars; full tracebacks are
    # never persisted — the sanitizer strips them before this column is set).
    error_summary: Mapped[str | None] = mapped_column(Text)

    # Auditable link to the primary downstream backtest (ON DELETE SET NULL —
    # the research trail survives even if the backtest run is deleted).
    backtest_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backtest_runs.id", ondelete="SET NULL")
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ResearchStep(Base):
    """One ordered step of a run, owned by an agent role.

    ``(run_id, sequence)`` is unique — a run has a linear audit trail. ``status``
    follows the step state machine (queued → running → terminal). ``attempt``
    supports retries (a retried step gets a new sequence or a bumped attempt).
    ``input_summary`` / ``output_summary`` are short structured snapshots, not
    full payloads — heavy artifacts live in downstream tables or the tool calls.
    """

    __tablename__ = "research_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_role: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    input_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentToolCall(Base):
    """One tool invocation within a step, with its own lifecycle and audit trail.

    ``tool_name`` must be in the FRA-84 :data:`~app.schemas.agent.KNOWN_TOOL_NAMES`
    allowlist. ``args_json`` / ``result_json`` are **sanitized** snapshots (the
    repository never persists raw secrets). Side-effect tools
    (``has_side_effects=True`` in the tool catalog) set ``idempotency_key``; a
    partial unique index on ``(step_id, idempotency_key)`` prevents a duplicate
    side-effect from being recorded (and thus from being retried) on the same
    step. ``evidence_refs`` points to downstream artifacts for reproducibility.
    """

    __tablename__ = "agent_tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("research_steps.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    # Validated tool args (sanitized) — the exact call the agent made.
    args_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Sanitized result snapshot — no secrets, no raw tracebacks.
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # References to downstream artifacts for reproducibility, e.g.
    # [{"type": "backtest_run", "id": "..."}, {"type": "factor_values", ...}].
    evidence_refs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    # Side-effect tools set this; partial unique index (step_id, idempotency_key)
    # prevents duplicate execution. Read-only tools leave it NULL.
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
