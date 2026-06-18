"""add backtest_runs.run_kind column (FRA-35)

区分单次触发回测与参数/成本 sweep 产出的子 run:
``backtest``(默认,POST /backtest 触发的常规回测)与 ``sensitivity``(FRA-35
sweep 为每个参数 × cost 组合产出的可复现 run)。配合 ``config_json.sweep``
网格记录,支撑 Week 2 MVP 的「结果入库可复现 + 可查询 sweep run」。

Revision ID: e4a2b7c91d3f
Revises: 128c1f90f78a
Create Date: 2026-06-18 10:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4a2b7c91d3f'
down_revision: Union[str, None] = '128c1f90f78a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'backtest_runs',
        sa.Column('run_kind', sa.String(length=16), nullable=False, server_default='backtest'),
    )


def downgrade() -> None:
    op.drop_column('backtest_runs', 'run_kind')
