"""add news and sentiment tables

Revision ID: e1a4b7c9d2f3
Revises: d8e6f0a2b3c4
Create Date: 2026-06-29 14:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "e1a4b7c9d2f3"
down_revision: Union[str, None] = "d8e6f0a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column(
            "id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("headline_hash", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("provider_id", sa.Text(), nullable=True),
        sa.Column("raw_payload", JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_id",
            "source",
            "published_at",
            "headline_hash",
            name="uq_news_items_asset_source_time_hash",
        ),
    )
    op.create_index(
        "ix_news_items_asset_id_published_at",
        "news_items",
        ["asset_id", "published_at"],
        unique=False,
    )
    op.create_index(
        "ix_news_items_source_published_at",
        "news_items",
        ["source", "published_at"],
        unique=False,
    )
    op.create_table(
        "sentiment_scores",
        sa.Column(
            "id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("news_item_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("raw_response", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "params",
            JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["news_item_id"], ["news_items.id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "news_item_id", "model_name", name="uq_sentiment_scores_news_model"
        ),
    )
    op.create_index(
        "ix_sentiment_scores_model_name_published_at",
        "sentiment_scores",
        ["model_name", "published_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sentiment_scores_model_name_published_at", table_name="sentiment_scores"
    )
    op.drop_index("ix_news_items_source_published_at", table_name="news_items")
    op.drop_index("ix_news_items_asset_id_published_at", table_name="news_items")
    op.drop_table("sentiment_scores")
    op.drop_table("news_items")
