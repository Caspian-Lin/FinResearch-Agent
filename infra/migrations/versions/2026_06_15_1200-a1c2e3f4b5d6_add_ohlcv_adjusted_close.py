"""add_ohlcv_adjusted_close

Revision ID: a1c2e3f4b5d6
Revises: 3fbe15cc698b
Create Date: 2026-06-15 12:00:00+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c2e3f4b5d6'
down_revision: Union[str, None] = '3fbe15cc698b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'ohlcv',
        sa.Column('adjusted_close', sa.Numeric(precision=20, scale=6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('ohlcv', 'adjusted_close')
