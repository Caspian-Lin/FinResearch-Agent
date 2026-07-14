"""OHLCV sync router (FRA-8).

Endpoints
---------
- ``POST /sync``          enqueue a sync job after validating inputs (202)
- ``GET  /sync/{job_id}`` return lifecycle + inputs + outcome (404 if job gone)

Week 1 uses RQ as the source of truth for job state; no ``data_sync_jobs``
table. Error summaries are sanitized (type + short message, no traceback).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from rq import Queue
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.asset import Asset
from app.schemas.sync import SyncEnqueueResponse, SyncJobStatus, SyncRequest
from app.services.datasources import SUPPORTED_SOURCES
from app.services.sync import (
    get_data_queue,
    map_rq_status,
    parse_job_inputs,
    safe_error_summary,
)

router = APIRouter(prefix="/sync", tags=["sync"])

DBSession = Annotated[Session, Depends(get_db)]
DataQueue = Annotated[Queue, Depends(get_data_queue)]

ALLOWED_SOURCES = SUPPORTED_SOURCES  # derived from the data-source registry (FRA-23)
MAX_SYNC_WINDOW_DAYS = 365 * 5  # ~5 years per request
SYNC_JOB_TIMEOUT = 600  # seconds
SYNC_RESULT_TTL = 86400  # keep job result 24h for GET polling


@router.post(
    "",
    response_model=SyncEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue an OHLCV sync job",
)
def enqueue_sync(payload: SyncRequest, db: DBSession, queue: DataQueue) -> SyncEnqueueResponse:
    """Validate inputs then enqueue ``worker.tasks.ohlcv.sync_ohlcv``.

    Returns ``202`` with the job id; the actual fetch/upsert runs on the worker.
    Asset existence, date ordering, source allow-list, and a max-window guard
    are all checked here so bad requests never consume a worker slot.
    """
    asset = db.get(Asset, payload.asset_id)
    if asset is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"Asset {payload.asset_id} not found."
        )
    if payload.start > payload.end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start must be <= end")
    if payload.source not in ALLOWED_SOURCES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"source must be one of {ALLOWED_SOURCES}",
        )
    if (payload.end - payload.start).days > MAX_SYNC_WINDOW_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sync window exceeds max {MAX_SYNC_WINDOW_DAYS} days",
        )
    job = queue.enqueue(
        "worker.tasks.ohlcv.sync_ohlcv",
        str(payload.asset_id),
        payload.start.isoformat(),
        payload.end.isoformat(),
        payload.source,
        job_timeout=SYNC_JOB_TIMEOUT,
        result_ttl=SYNC_RESULT_TTL,
    )
    return SyncEnqueueResponse(
        job_id=job.id,
        asset_id=payload.asset_id,
        start=payload.start,
        end=payload.end,
        source=payload.source,
    )


@router.get(
    "/{job_id}",
    response_model=SyncJobStatus,
    summary="Get sync job status",
)
def get_sync_status(job_id: str, queue: DataQueue) -> SyncJobStatus:
    """Return lifecycle, inputs, written/updated counts, and safe error.

    Inputs and result counts are pulled from ``job.args``/``job.result``; if the
    job has expired (``result_ttl`` elapsed) or never existed this returns
    ``404``. Error payloads never include a raw traceback.
    """
    job = queue.fetch_job(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Sync job {job_id} not found.")
    inputs = parse_job_inputs(job)
    result = (
        job.result
        if (job is not None and job.is_finished and isinstance(job.result, dict))
        else None
    )
    return SyncJobStatus(
        job_id=job.id,
        status=map_rq_status(job),
        asset_id=inputs.get("asset_id"),
        start=inputs.get("start"),
        end=inputs.get("end"),
        source=inputs.get("source"),
        inserted=result.get("inserted") if result else None,
        updated=result.get("updated") if result else None,
        total_bars=result.get("total_bars") if result else None,
        warning=result.get("warning") if result else None,
        error=safe_error_summary(job),
    )
