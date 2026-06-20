"""widen backtest_runs.run_kind for factor_sensitivity (FRA-54)

``run_kind`` was ``String(16)`` (FRA-35), enough for ``backtest`` /
``sensitivity`` but not for ``factor_sensitivity`` (18 chars) introduced by the
FRA-54 factor parameter/cost sweep. Widen to ``String(32)`` so the new sweep
kind can be persisted; a pure length widening is safe and non-destructive.

Revision ID: f4a1b2c3d4e5
Revises: dc9e240726b2
Create Date: 2026-06-21 09:20:00.000000+00:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f4a1b2c3d4e5"
down_revision: Union[str, None] = "dc9e240726b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "backtest_runs",
        "run_kind",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
        existing_server_default=sa.text("'backtest'"),
    )


def downgrade() -> None:
    op.alter_column(
        "backtest_runs",
        "run_kind",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'backtest'"),
    )
