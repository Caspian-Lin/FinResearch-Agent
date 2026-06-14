"""Pydantic v2 schemas for the OHLCV data-quality report (FRA-9)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class AnomalyPoint(BaseModel):
    """One detected anomaly on a single bar."""

    model_config = ConfigDict(from_attributes=True)

    time: datetime
    rule: str  # non_positive_price | high_lt_low | negative_volume | zero_volume | large_return
    detail: str | None = None


class QualityReport(BaseModel):
    """On-demand quality report for one (asset, source, [start, end]) window."""

    model_config = ConfigDict(from_attributes=True)

    asset_id: uuid.UUID
    source: str
    start: date
    end: date
    expected_sessions: int
    observed_sessions: int
    missing_sessions_count: int
    coverage: float  # observed/expected in [0, 1]; 0.0 when expected == 0
    missing_sessions: list[date]
    anomalies: list[AnomalyPoint]
