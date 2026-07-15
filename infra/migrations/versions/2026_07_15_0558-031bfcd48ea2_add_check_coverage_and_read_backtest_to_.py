"""add check_coverage and read_backtest to tool_name check

Revision ID: 031bfcd48ea2
Revises: f8a2b9c1d3e5
Create Date: 2026-07-15 05:58:55.605251+00:00

FRA-87 introduced ``check_coverage`` and ``read_backtest`` as registered agent
tools, but the DB check constraint on ``agent_tool_calls.tool_name`` (created in
FRA-85) was not updated. This migration adds the two new tool names to the
allowlist so the Orchestrator (FRA-90) can persist calls to them.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "031bfcd48ea2"
down_revision: Union[str, None] = "f8a2b9c1d3e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TOOL_NAMES = (
    "'resolve_assets', 'check_coverage', 'sync_ohlcv', 'sync_news', "
    "'compute_factor', 'evaluate_factor', "
    "'run_backtest', 'read_backtest', 'run_comparison', "
    "'run_risk_checks', 'cost_sensitivity_sweep', 'generate_memo'"
)


def upgrade() -> None:
    op.drop_constraint("agent_tool_calls_tool_name_check", "agent_tool_calls", type_="check")
    op.create_check_constraint(
        "agent_tool_calls_tool_name_check",
        "agent_tool_calls",
        f"tool_name IN ({_TOOL_NAMES})",
    )


def downgrade() -> None:
    _OLD_TOOL_NAMES = (
        "'resolve_assets', 'sync_ohlcv', 'sync_news', 'compute_factor', "
        "'evaluate_factor', 'run_backtest', 'run_comparison', 'run_risk_checks', "
        "'cost_sensitivity_sweep', 'generate_memo'"
    )
    op.drop_constraint("agent_tool_calls_tool_name_check", "agent_tool_calls", type_="check")
    op.create_check_constraint(
        "agent_tool_calls_tool_name_check",
        "agent_tool_calls",
        f"tool_name IN ({_OLD_TOOL_NAMES})",
    )
