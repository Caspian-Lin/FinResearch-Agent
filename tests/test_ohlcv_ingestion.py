"""Tests for OHLCV data ingestion. Placeholder until Week 1 implementation."""

import pytest


@pytest.mark.skip(reason="Week 1 — sync job not yet implemented")
def test_sync_ohlcv_job_inserts_bars() -> None:
    """Syncing OHLCV for an asset should insert rows into ohlcv."""
    # TODO: implement when data sync worker is added
