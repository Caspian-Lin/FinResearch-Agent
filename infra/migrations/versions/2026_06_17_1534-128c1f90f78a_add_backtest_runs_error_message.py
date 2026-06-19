"""add backtest_runs.error_message column (FRA-37)

失败原因持久化:worker ``run_backtest_job`` 失败时把异常摘要(≤500 字符)
写入此列,供 ``GET /backtest/{run_id}`` (FRA-36) 展示。success / running 时
为 NULL。

Revision ID: 128c1f90f78a
Revises: c3c37d0ffaf4
Create Date: 2026-06-17 15:34:02.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '128c1f90f78a'
down_revision: Union[str, None] = 'c3c37d0ffaf4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'backtest_runs', sa.Column('error_message', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('backtest_runs', 'error_message')
