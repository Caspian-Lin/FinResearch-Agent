"""add backtest tables

Revision ID: aca75754a605
Revises: a1c2e3f4b5d6
Create Date: 2026-06-16 16:31:34.903412+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aca75754a605'
down_revision: Union[str, None] = 'a1c2e3f4b5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # backtest_runs — one row per run; config_json is the 1:1 reproducible
    # parameter snapshot (mirrors the FRA-25 BacktestConfig).
    op.create_table('backtest_runs',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('strategy_type', sa.String(length=64), nullable=False),
        sa.Column('config_json', sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column('benchmark_asset_id', sa.UUID(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('price_field', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['benchmark_asset_id'], ['assets.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )

    # backtest_metrics — 1:1 with backtest_runs; gross_* (pre-cost) + net_*
    # (post-cost) for each of the 9 §11.2 metrics.
    op.create_table('backtest_metrics',
        sa.Column('backtest_run_id', sa.UUID(), nullable=False),
        sa.Column('gross_annual_return', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('gross_volatility', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('gross_sharpe_ratio', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('gross_max_drawdown', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('gross_calmar_ratio', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('gross_turnover', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('gross_win_rate', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('gross_beta', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('gross_correlation', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('net_annual_return', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('net_volatility', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('net_sharpe_ratio', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('net_max_drawdown', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('net_calmar_ratio', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('net_turnover', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('net_win_rate', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('net_beta', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('net_correlation', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.ForeignKeyConstraint(['backtest_run_id'], ['backtest_runs.id'], ),
        sa.PrimaryKeyConstraint('backtest_run_id'),
    )

    # equity_curve — TimescaleDB hypertable partitioned by time; composite PK
    # (backtest_run_id, time) satisfies the hypertable partition-column rule
    # and doubles as the (run_id, time) lookup index.
    op.create_table('equity_curve',
        sa.Column('backtest_run_id', sa.UUID(), nullable=False),
        sa.Column('time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('equity', sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column('daily_return', sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column('drawdown', sa.Numeric(precision=10, scale=6), nullable=True),
        sa.ForeignKeyConstraint(['backtest_run_id'], ['backtest_runs.id'], ),
        sa.PrimaryKeyConstraint('backtest_run_id', 'time'),
    )
    op.execute("SELECT create_hypertable('equity_curve', 'time');")

    # trades — one rebalance fill per row.
    op.create_table('trades',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('backtest_run_id', sa.UUID(), nullable=False),
        sa.Column('time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('asset_id', sa.UUID(), nullable=False),
        sa.Column('side', sa.String(length=8), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column('price', sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column('cost', sa.Numeric(precision=20, scale=6), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ),
        sa.ForeignKeyConstraint(['backtest_run_id'], ['backtest_runs.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trades_run_time', 'trades', ['backtest_run_id', 'time'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_trades_run_time', table_name='trades')
    op.drop_table('trades')
    op.drop_table('equity_curve')
    op.drop_table('backtest_metrics')
    op.drop_table('backtest_runs')
