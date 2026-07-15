"""Agent research worker task (FRA-90).

Thin RQ entrypoint that delegates to the orchestrator service layer. All real
logic lives in ``app.services.agent.orchestrator`` so the API and tests can call
it without the worker.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.db.session import SessionLocal
from app.models.agent import ResearchRun
from app.schemas.agent import AgentRunStatus
from app.services.agent.orchestrator import run_research
from app.services.agent.repository import AgentRunRepository

logger = logging.getLogger(__name__)


def run_research_job(run_id: str) -> dict[str, Any]:
    """RQ task: execute a research run to completion.

    Opens its own DB session (independent of the API's session), runs the
    orchestrator, and on unexpected exception transitions the run to ``failed``
    with a safe error summary (no traceback) before re-raising for RQ.
    """
    rid = uuid.UUID(run_id)
    db = SessionLocal()
    try:
        # Load the run to get user_id.
        run = db.get(ResearchRun, rid)
        if run is None:
            raise ValueError(f"research run {run_id} not found")

        status = run_research(rid, run.user_id, db=db)
        logger.info("research run %s completed with status=%s", run_id, status)
        return {"run_id": run_id, "status": status}

    except Exception as exc:
        logger.exception("research run %s failed", run_id)
        # Best-effort failure transition.
        try:
            repo = AgentRunRepository(db)
            run = db.get(ResearchRun, rid)
            if run is not None and AgentRunStatus(run.status) == AgentRunStatus.RUNNING:
                msg = str(exc)[:500]
                repo.transition_run(rid, run.user_id, AgentRunStatus.FAILED, error_summary=msg)
        except Exception:
            logger.exception("failed to mark run %s as failed", run_id)
        raise

    finally:
        db.close()
