"""RQ queue factory + sync-job status mapping (FRA-8).

Week 1 uses RQ itself as the source of truth for sync job state — no
``data_sync_jobs`` table is introduced (per FRA-8 non-goals).
"""

from __future__ import annotations

from typing import Any

from redis import Redis
from rq import Queue
from rq.job import Job

from app.core.config import settings

_queue: Queue | None = None


def get_data_queue() -> Queue:
    """Return a singleton RQ Queue bound to the ``data_sync`` queue + redis.

    The connection is lazily built from ``settings.redis_url`` on first call
    and cached for the lifetime of the process so repeated ``enqueue``/``fetch``
    calls reuse the same Redis client.
    """
    global _queue
    if _queue is None:
        connection = Redis.from_url(settings.redis_url)
        _queue = Queue(name=settings.rq_queue_data, connection=connection)
    return _queue


_backtest_queue: Queue | None = None


def get_backtest_queue() -> Queue:
    """Return a singleton RQ Queue bound to the ``backtest`` queue (FRA-36/37).

    Lazy + cached, mirroring :func:`get_data_queue`. ``POST /backtest`` enqueues
    ``worker.tasks.backtest.run_backtest_job`` here; the worker listens on this
    queue (see ``worker/main.py``).
    """
    global _backtest_queue
    if _backtest_queue is None:
        connection = Redis.from_url(settings.redis_url)
        _backtest_queue = Queue(name=settings.rq_queue_backtest, connection=connection)
    return _backtest_queue


def map_rq_status(job: Job | None) -> str:
    """Map an RQ job to pending | running | success | success_no_data | failed.

    A ``None`` job (e.g. expired result) is treated as ``pending`` so the caller
    can decide whether to surface it differently; finished-but-failed wins over
    finished so exception state is never hidden behind a success marker. Finished
    sync jobs may carry a domain status in ``job.result["status"]``; preserve
    ``success_no_data`` so an empty provider response is not reported as success.
    """
    if job is None:
        return "pending"
    if job.is_failed:
        return "failed"
    if job.is_finished:
        if isinstance(job.result, dict) and job.result.get("status") == "success_no_data":
            return "success_no_data"
        return "success"
    if job.is_started:
        return "running"
    return "pending"  # queued / scheduled / deferred


def safe_error_summary(job: Job | None) -> dict[str, str] | None:
    """Return a sanitized error summary for a failed job (no raw traceback).

    RQ stores the full ``exc_info`` string on a failed job; exposing that to
    clients would leak internals and stack paths. Instead we surface only the
    final line (``ExceptionType: message``), truncated to 200 chars, parsed into
    ``{"type", "message"}`` when a ``:`` separator is present.
    """
    if job is None or not job.is_failed or not job.exc_info:
        return None
    lines = (job.exc_info or "").strip().splitlines()
    last_line = lines[-1] if lines else "Unknown error"
    if ":" in last_line:
        typ, _, msg = last_line.partition(":")
        return {"type": typ.strip(), "message": msg.strip()[:200]}
    return {"type": "Error", "message": last_line.strip()[:200]}


def parse_job_inputs(job: Job | None) -> dict[str, Any]:
    """Parse ``[asset_id_str, start_str, end_str, source]`` from ``job.args``.

    RQ serializes args through Redis, so the API enqueues them as strings; we
    parse them back into typed values here for the status response. Any
    malformed/missing payload yields an empty dict rather than raising, so a
    corrupt job never breaks ``GET /sync/{job_id}``.
    """
    import uuid as _uuid
    from datetime import date as _date

    if job is None or not job.args:
        return {}
    args = job.args
    try:
        return {
            "asset_id": _uuid.UUID(str(args[0])),
            "start": _date.fromisoformat(str(args[1])),
            "end": _date.fromisoformat(str(args[2])),
            "source": str(args[3]) if len(args) > 3 else "yfinance",
        }
    except (IndexError, ValueError, TypeError):
        return {}
