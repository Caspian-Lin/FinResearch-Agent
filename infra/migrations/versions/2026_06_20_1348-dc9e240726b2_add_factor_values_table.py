"""add factor values table

Revision ID: dc9e240726b2
Revises: e4a2b7c91d3f
Create Date: 2026-06-20 13:48:49.045417+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "dc9e240726b2"
down_revision: Union[str, None] = "e4a2b7c91d3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "factor_values",
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("factor_name", sa.Text(), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("asset_id", "factor_name", "time", "source"),
    )
    op.execute("SELECT create_hypertable('factor_values', 'time');")
    op.create_index(
        "ix_factor_values_factor_name_time",
        "factor_values",
        ["factor_name", "time"],
        unique=False,
    )
    op.create_index(
        "ix_factor_values_asset_id_time",
        "factor_values",
        ["asset_id", "time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_factor_values_asset_id_time", table_name="factor_values")
    op.drop_index("ix_factor_values_factor_name_time", table_name="factor_values")
    op.drop_table("factor_values")
