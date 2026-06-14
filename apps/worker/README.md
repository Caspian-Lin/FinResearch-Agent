# @finresearch/worker — Background Worker

RQ-based background worker that consumes jobs from Redis queues:

| Queue | Purpose |
|---|---|
| `default` | Generic tasks |
| `data_sync` | OHLCV / fundamentals / news ingestion |
| `backtest` | Strategy backtest execution |

## Layout

```text
apps/worker/
  worker/
    main.py            # RQ worker entrypoint
    config.py          # Worker settings (reuses API config where possible)
    tasks/
      __init__.py
      sync_ohlcv.py    # yfinance OHLCV ingestion (Week 1)
      quality.py       # Data quality check tasks
      backtest.py      # Backtest runner tasks (Week 2)
      report.py        # Research memo generation (Week 5-6)
  pyproject.toml
  Dockerfile
```

## Local Development

```bash
# From repo root
make worker-dev
# Or via Docker
make up SERVICE=worker
make logs SERVICE=worker
```

## Queueing a Job (from API)

```python
from redis import Redis
from rq import Queue

from app.core.config import settings

redis = Redis.from_url(settings.redis_url)
queue = Queue(settings.rq_queue_data, connection=redis)
queue.enqueue("worker.tasks.sync_ohlcv.sync_asset", asset_id, start, end)
```
