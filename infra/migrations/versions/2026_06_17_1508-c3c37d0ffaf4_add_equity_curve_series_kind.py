"""add equity_curve.series_kind column + composite PK (FRA-41)

让 benchmark(buy & hold)曲线能与策略曲线同表共存:新增 ``series_kind``
列('strategy' | 'benchmark'),并把主键从 ``(backtest_run_id, time)`` 改为
``(backtest_run_id, series_kind, time)`` —— 同 run 同时刻可并存两条曲线。
``time`` 仍在主键内,满足 TimescaleDB hypertable 分区列要求。

Revision ID: c3c37d0ffaf4
Revises: aca75754a605
Create Date: 2026-06-17 15:08:14.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3c37d0ffaf4'
down_revision: Union[str, None] = 'aca75754a605'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) series_kind:'strategy'(本策略曲线)| 'benchmark'(buy&hold 基准,FRA-41)。
    #    NOT NULL + server_default 'strategy' → 现有行回填,后续缺省插入为策略行。
    op.add_column(
        'equity_curve',
        sa.Column(
            'series_kind', sa.String(length=16), nullable=False, server_default='strategy'
        ),
    )
    # 2) 主键 (run_id, time) → (run_id, series_kind, time):同 run 同时刻可并存
    #    strategy + benchmark。time 仍在主键(hypertable 分区列必须属主键)。
    op.drop_constraint('equity_curve_pkey', 'equity_curve', type_='primary')
    op.create_primary_key(
        'equity_curve_pkey', 'equity_curve', ['backtest_run_id', 'series_kind', 'time']
    )


def downgrade() -> None:
    op.drop_constraint('equity_curve_pkey', 'equity_curve', type_='primary')
    op.create_primary_key('equity_curve_pkey', 'equity_curve', ['backtest_run_id', 'time'])
    op.drop_column('equity_curve', 'series_kind')
