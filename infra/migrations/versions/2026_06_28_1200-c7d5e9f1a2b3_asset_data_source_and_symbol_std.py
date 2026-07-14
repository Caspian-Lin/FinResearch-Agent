"""add assets.data_source/list_status + standardize symbol suffixes (FRA-78)

FRA-78 unifies the asset symbol convention to an exchange-suffix form
(``600519.SH`` / ``000001.SZ`` / ``430017.BJ`` / ``00700.HK`` / ``AAPL.O`` /
``JPM.N`` / ``SPY.A``) and records each asset's preferred data source so the
dispatcher (:mod:`app.services.datasources`) can route fetches without
re-deriving it from the exchange every call.

Two new NOT NULL columns are added with safe server defaults so existing rows
are populated in-place:

* ``data_source`` (String(32), default ``yfinance``) — the canonical source
  name (``yfinance`` / ``akshare`` / ``tushare``). A-share rows (``.SH`` /
  ``.SZ`` / ``.BJ``) are then flipped to ``akshare``; everything else keeps
  the ``yfinance`` default.
* ``list_status`` (String(16), default ``active``) — ``active`` /
  ``suspended`` / ``delisted`` trading state.

Symbol data migration is run as idempotent SQL via :func:`op.execute`:

* A-shares: legacy ``.SS`` suffix → ``.SH`` (the SSE exchange code used in the
  unified convention). The ``LIKE '%.SS'`` predicate only matches the bare
  yfinance-style suffix and is a no-op once rows already carry ``.SH``.
* US: NASDAQ/NYSE/AMEX bare tickers gain ``.O``/``.N``/``.A`` respectively.
  ``symbol NOT LIKE '%.%'`` keeps already-suffixed rows untouched, so the
  statement is safe to re-run.

The downgrade only drops the two new columns; it intentionally does NOT revert
the symbol edits — rewinding ``.SH``→``.SS`` would lose information and the
suffix migration is forward-only. Roll back to a pre-FRA-78 backup if the old
symbol shape is required.

Revision ID: c7d5e9f1a2b3
Revises: a5b3c4d7e8f9
Create Date: 2026-06-28 12:00:00.000000+00:00

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d5e9f1a2b3"
down_revision: Union[str, None] = "a5b3c4d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New columns with safe server defaults so existing rows are backfilled
    #    in place (data_source defaults to yfinance; A-shares overridden below).
    op.add_column(
        "assets",
        sa.Column(
            "data_source",
            sa.String(length=32),
            nullable=False,
            server_default="yfinance",
        ),
    )
    op.add_column(
        "assets",
        sa.Column(
            "list_status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
    )

    # 2. Symbol data migration — order matters: rewrite A-share suffixes first
    #    (so the .SH/.SZ/.BJ data_source rule below matches the post-migration
    #    shape), then decorate bare US tickers. Every statement is idempotent:
    #    the LIKE / NOT LIKE guards make re-runs no-ops.
    # A-shares: legacy yfinance-style .SS → unified .SH (SSE exchange code).
    op.execute("UPDATE assets SET symbol = replace(symbol, '.SS', '.SH') WHERE symbol LIKE '%.SS';")
    # Preferred source by suffix: A-shares (.SH/.SZ/.BJ) → akshare; everything
    # else keeps the column default (yfinance).
    op.execute(
        "UPDATE assets SET data_source = 'akshare' "
        "WHERE symbol LIKE '%.SH' OR symbol LIKE '%.SZ' OR symbol LIKE '%.BJ';"
    )
    # US bare tickers gain their exchange suffix. NOT LIKE '%.%' guarantees
    # already-suffixed rows (e.g. a re-run, or a pre-suffixed seed) are left
    # untouched — the statement is safe to apply repeatedly.
    op.execute(
        "UPDATE assets SET symbol = symbol || '.O' "
        "WHERE exchange = 'NASDAQ' AND symbol NOT LIKE '%.%';"
    )
    op.execute(
        "UPDATE assets SET symbol = symbol || '.N' "
        "WHERE exchange = 'NYSE' AND symbol NOT LIKE '%.%';"
    )
    op.execute(
        "UPDATE assets SET symbol = symbol || '.A' "
        "WHERE exchange = 'AMEX' AND symbol NOT LIKE '%.%';"
    )


def downgrade() -> None:
    # Drop the two new columns. The symbol edits above are forward-only and
    # are intentionally NOT reverted (rewinding .SH → .SS would discard the
    # unified-suffix information; restore from a pre-FRA-78 backup if needed).
    op.drop_column("assets", "list_status")
    op.drop_column("assets", "data_source")
