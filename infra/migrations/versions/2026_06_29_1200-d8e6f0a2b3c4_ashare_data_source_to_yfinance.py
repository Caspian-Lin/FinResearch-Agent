"""switch A-share data_source akshare→yfinance (FRA-83)

FRA-79 assigned A-shares ``data_source='akshare'`` (the user's "akshare 主力"
choice), but empirical testing later showed akshare's OHLCV endpoint
``stock_zh_a_hist`` is rate-limited / anti-scraped and returns empty in
practice (工商银行 ``sh601398`` → ``shape (0,0)``), while yfinance can pull
A-share daily bars via the ``.SS``/``.SZ`` ticker form (``601398.SS`` → 9
bars verified).

Decision (FRA-83): akshare stays the *universe source* — FRA-79 still uses it
to list A/HK/US instruments + delisted flags — but yfinance becomes the *bar
source* for all markets including A-shares. This migration flips every
``data_source='akshare'`` row to ``'yfinance'`` so the worker fetches A-share
bars from yfinance instead of timing out on akshare.

The statement is idempotent (a no-op once no rows carry ``'akshare'``). The
downgrade is best-effort: it rewinds A-share suffix rows (``.SH``/``.SZ``/
``.BJ``) back to ``'akshare'``; HK/US rows were never ``'akshare'`` so they
are left untouched.

Revision ID: d8e6f0a2b3c4
Revises: c7d5e9f1a2b3
Create Date: 2026-06-29 12:00:00.000000+00:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e6f0a2b3c4"
down_revision: Union[str, None] = "c7d5e9f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # akshare → yfinance for every row (empirically A-shares; HK/US were
    # already 'yfinance'). Idempotent: no-op once no 'akshare' rows remain.
    op.execute("UPDATE assets SET data_source = 'yfinance' WHERE data_source = 'akshare';")


def downgrade() -> None:
    # Best-effort: rewind only A-share suffix rows back to 'akshare'. HK/US
    # rows were never 'akshare' and stay 'yfinance'.
    op.execute(
        "UPDATE assets SET data_source = 'akshare' "
        "WHERE symbol LIKE '%.SH' OR symbol LIKE '%.SZ' OR symbol LIKE '%.BJ';"
    )
