"""add agent run persistence (research_runs, research_steps, agent_tool_calls)

Revision ID: f8a2b9c1d3e5
Revises: e1a4b7c9d2f3
Create Date: 2026-07-15 12:00:00.000000+00:00

Three new tables back the Week 5 research-agent run log (FRA-85):

* ``research_runs``    — one row per research run (user ownership, versioned
  plan JSON + hash, run lifecycle, planner provenance, synthesis, error
  summary, downstream backtest link).
* ``research_steps``   — ordered steps within a run (UNIQUE ``run_id, sequence``).
* ``agent_tool_calls`` — individual tool invocations (partial unique index on
  ``step_id, idempotency_key`` for side-effect idempotency).

CHECK constraints enforce the FRA-84 state-machine allowlists at the DB layer
(defense in depth); FKs cascade so deleting a run purges its steps and tool
calls without orphan rows. ``backtest_run_id`` uses ON DELETE SET NULL so the
research trail survives a backtest deletion.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "f8a2b9c1d3e5"
down_revision: Union[str, None] = "e1a4b7c9d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ── FRA-84 allowlist literals (duplicated here because migrations are static) ──
_RUN_STATUSES = "'draft', 'validated', 'queued', 'running', 'succeeded', 'failed', 'canceled'"
_STEP_STATUSES = "'queued', 'running', 'succeeded', 'failed', 'canceled'"
_AGENT_ROLES = (
    "'research_planner', 'data_agent', 'factor_agent', "
    "'backtest_agent', 'risk_agent', 'report_agent'"
)
_TOOL_NAMES = (
    "'resolve_assets', 'sync_ohlcv', 'sync_news', 'compute_factor', "
    "'evaluate_factor', 'run_backtest', 'run_comparison', 'run_risk_checks', "
    "'cost_sensitivity_sweep', 'generate_memo'"
)


def upgrade() -> None:
    # ── research_runs ────────────────────────────────────────────────────────
    op.create_table(
        "research_runs",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("research_question", sa.Text(), nullable=False),
        sa.Column("plan_schema_version", sa.String(16), nullable=False),
        sa.Column("plan_json", JSONB, nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("planner_provider", sa.String(64), nullable=True),
        sa.Column("planner_model", sa.String(128), nullable=True),
        sa.Column("planner_prompt_version", sa.String(64), nullable=True),
        sa.Column("synthesis_json", JSONB, nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("backtest_run_id", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(f"status IN ({_RUN_STATUSES})", name="research_runs_status_check"),
    )
    op.create_index("ix_research_runs_user_id", "research_runs", ["user_id"], unique=False)
    op.create_index(
        "ix_research_runs_user_id_status", "research_runs", ["user_id", "status"], unique=False
    )
    op.create_index("ix_research_runs_plan_hash", "research_runs", ["plan_hash"], unique=False)

    # ── research_steps ───────────────────────────────────────────────────────
    op.create_table(
        "research_steps",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("agent_role", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("input_summary", JSONB, nullable=True),
        sa.Column("output_summary", JSONB, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="research_steps_run_id_sequence_key"),
        sa.CheckConstraint(f"status IN ({_STEP_STATUSES})", name="research_steps_status_check"),
        sa.CheckConstraint(
            f"agent_role IN ({_AGENT_ROLES})", name="research_steps_agent_role_check"
        ),
    )
    op.create_index("ix_research_steps_run_id", "research_steps", ["run_id"], unique=False)

    # ── agent_tool_calls ─────────────────────────────────────────────────────
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("step_id", sa.UUID(), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("tool_version", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("args_json", JSONB, nullable=True),
        sa.Column("result_json", JSONB, nullable=True),
        sa.Column("evidence_refs", JSONB, nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["step_id"], ["research_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(f"status IN ({_STEP_STATUSES})", name="agent_tool_calls_status_check"),
        sa.CheckConstraint(
            f"tool_name IN ({_TOOL_NAMES})", name="agent_tool_calls_tool_name_check"
        ),
    )
    op.create_index("ix_agent_tool_calls_step_id", "agent_tool_calls", ["step_id"], unique=False)
    # Partial unique index: a side-effect tool (idempotency_key IS NOT NULL) may
    # only appear once per step — prevents duplicate execution / double-write.
    op.create_index(
        "agent_tool_calls_step_id_idempotency_key_key",
        "agent_tool_calls",
        ["step_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("agent_tool_calls_step_id_idempotency_key_key", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_step_id", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")

    op.drop_index("ix_research_steps_run_id", table_name="research_steps")
    op.drop_table("research_steps")

    op.drop_index("ix_research_runs_plan_hash", table_name="research_runs")
    op.drop_index("ix_research_runs_user_id_status", table_name="research_runs")
    op.drop_index("ix_research_runs_user_id", table_name="research_runs")
    op.drop_table("research_runs")
