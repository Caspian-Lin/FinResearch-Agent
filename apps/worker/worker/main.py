"""RQ worker entrypoint.

Listens on three queues: default, data_sync, backtest. Will pick up any
job enqueued by the API service.

Run locally:
    cd apps/worker && python -m worker.main

In Docker:
    docker compose up worker
"""

from __future__ import annotations

import logging
import os
import sys

from redis import Redis
from rq import Queue, Worker

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        stream=sys.stdout,
    )


def main() -> int:
    """Start RQ worker listening on configured queues."""
    _configure_logging()

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    connection = Redis.from_url(redis_url)

    queues = [
        os.getenv("RQ_QUEUE_DEFAULT", "default"),
        os.getenv("RQ_QUEUE_DATA", "data_sync"),
        os.getenv("RQ_QUEUE_BACKTEST", "backtest"),
    ]

    logger.info("Starting RQ worker on queues=%s redis=%s", queues, redis_url)
    worker = Worker(
        [Queue(name=q, connection=connection) for q in queues],
        connection=connection,
    )
    worker.work(with_scheduler=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
