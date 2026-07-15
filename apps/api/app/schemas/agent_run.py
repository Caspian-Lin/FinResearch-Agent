"""Request/response schemas for the Agent REST API (FRA-90).

These are the wire-level types for ``/agent/plans``, ``/agent/runs``, and
``/agent/runs/{id}/trace`` endpoints. They are intentionally thin — the
canonical plan contract lives in :mod:`app.schemas.agent`, and the synthesis
schema lives in :mod:`app.services.agent.report`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent import ResearchPlan

# ─── Plan endpoint ───────────────────────────────────────────────────────────


class AgentPlanRequest(BaseModel):
    """Body for ``POST /agent/plans``."""

    model_config = ConfigDict(extra="forbid")

    hypothesis: str = Field(min_length=1, description="Natural-language investment hypothesis.")


class AgentPlanResponse(BaseModel):
    """Response for ``POST /agent/plans`` — a plan draft (no side effects).

    The endpoint does **not** create a run; the caller submits the returned
    plan + ``plan_hash`` to ``POST /agent/runs`` to approve and enqueue.
    """

    model_config = ConfigDict(extra="forbid")

    research_question: str
    plan: ResearchPlan | None = Field(
        default=None,
        description="Validated plan; None when the hypothesis is ambiguous or invalid.",
    )
    plan_hash: str | None = Field(
        default=None,
        description="SHA-256 hash of the canonical plan JSON. Required to enqueue.",
    )
    clarification_needed: str | None = Field(
        default=None,
        description="Human-readable guidance when the hypothesis is ambiguous.",
    )
    validation_errors: list[str] = Field(
        default_factory=list,
        description="Non-empty when the planner output failed contract validation.",
    )
    planner_provider: str | None = None
    planner_model: str | None = None


# ─── Run creation ────────────────────────────────────────────────────────────


class AgentRunCreateRequest(BaseModel):
    """Body for ``POST /agent/runs`` — submit an approved plan for execution."""

    model_config = ConfigDict(extra="forbid")

    plan: ResearchPlan = Field(description="The plan returned by POST /agent/plans.")
    plan_hash: str = Field(
        description="The plan_hash from POST /agent/plans; must match the plan.",
    )


class AgentRunEnqueuedResponse(BaseModel):
    """Response for ``POST /agent/runs`` — the run has been queued."""

    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    status: str = Field(description="'queued'.")
    plan_hash: str


# ─── Run detail / list ───────────────────────────────────────────────────────


class AgentRunSummary(BaseModel):
    """Compact run summary for list responses."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    research_question: str
    status: str
    plan_hash: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_summary: str | None = None
    current_step: str | None = Field(
        default=None,
        description="Agent role of the current/last step (for progress display).",
    )


class AgentRunDetail(AgentRunSummary):
    """Full run detail with plan + synthesis."""

    model_config = ConfigDict(extra="forbid")

    plan: ResearchPlan | None = None
    synthesis: dict[str, Any] | None = Field(
        default=None,
        description="Research synthesis (present once status='succeeded').",
    )
    step_count: int = Field(default=0, description="Total steps recorded.")
    completed_steps: int = Field(default=0, description="Steps in terminal status.")


class AgentRunListResponse(BaseModel):
    """Paginated list of a user's runs."""

    model_config = ConfigDict(extra="forbid")

    runs: list[AgentRunSummary]
    total: int
    limit: int
    offset: int


# ─── Trace ───────────────────────────────────────────────────────────────────


class ToolCallTrace(BaseModel):
    """One tool call in the trace, sanitized."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    tool_name: str
    status: str
    args: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    evidence_refs: list[dict[str, Any]] | None = None
    duration_ms: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class StepTrace(BaseModel):
    """One step in the trace, with nested tool calls."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    sequence: int
    agent_role: str
    kind: str
    status: str
    input_summary: dict[str, Any] | None = None
    output_summary: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)


class AgentTraceResponse(BaseModel):
    """Full trace for a run — ordered steps with nested tool calls."""

    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    run_status: str
    steps: list[StepTrace]


# ─── Cancel ──────────────────────────────────────────────────────────────────


class AgentCancelResponse(BaseModel):
    """Response for ``POST /agent/runs/{id}/cancel``."""

    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    status: str = Field(description="'canceled' (terminal) or the pre-existing terminal status.")
    message: str = Field(description="Idempotent confirmation.")


__all__ = [
    "AgentCancelResponse",
    "AgentPlanRequest",
    "AgentPlanResponse",
    "AgentRunCreateRequest",
    "AgentRunDetail",
    "AgentRunEnqueuedResponse",
    "AgentRunListResponse",
    "AgentRunSummary",
    "AgentTraceResponse",
    "StepTrace",
    "ToolCallTrace",
]
