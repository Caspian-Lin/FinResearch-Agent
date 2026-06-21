"""add backtest_runs.result_json for factor worker jobs (FRA-57)

The FRA-57 factor worker enqueues three async job kinds (``factor_compute`` /
``factor_quantile`` / ``factor_sweep``) that reuse the ``backtest_runs`` state
machine (pending → running → success/failed). Unlike a regular backtest — whose
outputs land in ``backtest_metrics`` / ``equity_curve`` / ``trades`` — these jobs
produce structured results (row counts, per-quantile equity series, a sensitivity
summary grid) that have no dedicated table. ``result_json`` stores that blob on
the run row itself so ``GET /factors/jobs/{run_id}`` can return it in one read.

The column is nullable: existing runs and pending/running rows are unaffected,
and only the factor worker writes it on success.

Revision ID: a5b3c4d7e8f9
Revises: f4a1b2c3d4e5
Create Date: 2026-06-21 10:30:00.000000+00:00

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "a5b3c4d7e8f9"
down_revision: Union[str, None] = "f4a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "backtest_runs",
        sa.Column("result_json", JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("backtest_runs", "result_json")
