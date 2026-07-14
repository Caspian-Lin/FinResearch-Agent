"""Real-DB tests for agent run persistence (FRA-85).

Covers the repository layer's three invariants: user-scoped ownership
(cross-user → :class:`AgentRunNotFoundError`), state-machine integrity (legal /
illegal transitions, terminal irreversibility), and the secret boundary
(args / result sanitized before flush). Also exercises sequence uniqueness,
idempotency-key deduplication, partial completion, and cancellation.

Mirrors ``test_backtest_models.py``: the host Postgres is used directly with
surgical cleanup scoped to the ``FRA85TEST`` prefix.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from app.db.session import SessionLocal
from app.models.agent import ResearchRun
from app.models.asset import Asset
from app.models.backtest import BacktestRun
from app.models.user import User
from app.schemas.agent import AgentRunStatus, AgentStepStatus, IllegalStateTransitionError
from app.services.agent.repository import (
    AgentRunNotFoundError,
    AgentRunRepository,
    DuplicateToolCallError,
    compute_plan_hash,
)
from app.services.agent.sanitizer import REDACTED
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

PREFIX = "FRA85TEST"


# ---------------------------------------------------------------------------
# DB helpers + fixtures
# ---------------------------------------------------------------------------


def _cleanup(db: Session) -> None:
    runs = "SELECT id FROM research_runs WHERE research_question LIKE :p"
    steps = f"SELECT id FROM research_steps WHERE run_id IN ({runs})"
    db.execute(
        text(f"DELETE FROM agent_tool_calls WHERE step_id IN ({steps})"),
        {"p": f"{PREFIX}%"},
    )
    db.execute(text(f"DELETE FROM research_steps WHERE run_id IN ({runs})"), {"p": f"{PREFIX}%"})
    db.execute(
        text("DELETE FROM research_runs WHERE research_question LIKE :p"), {"p": f"{PREFIX}%"}
    )
    db.execute(text("DELETE FROM backtest_runs WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
    db.execute(text("DELETE FROM assets WHERE symbol LIKE :p"), {"p": f"{PREFIX}%"})
    db.execute(text("DELETE FROM users WHERE email LIKE :p"), {"p": f"{PREFIX}%"})
    db.commit()


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)
        db.close()


def _make_user(db: Session, suffix: str = "U1") -> User:
    user = User(email=f"{PREFIX}-{suffix}@test", hashed_password="x", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_asset(db: Session, symbol: str = "FRA85TEST-A") -> Asset:
    asset = Asset(
        symbol=symbol,
        name=f"Test {symbol}",
        exchange="NASDAQ",
        asset_type="stock",
        currency="USD",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _plan(question: str = "FRA85TEST question") -> dict[str, object]:
    return {"schema_version": "1.0", "research_question": question, "data": [1, 2, 3]}


def _make_run(
    repo: AgentRunRepository, user: User, question: str = "FRA85TEST question"
) -> ResearchRun:
    return repo.create_run(user_id=user.id, research_question=question, plan=_plan(question))


# ---------------------------------------------------------------------------
# create_run: defaults, plan hash, ownership
# ---------------------------------------------------------------------------


def test_create_run_defaults_and_plan_hash(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = repo.create_run(user_id=user.id, research_question="FRA85TEST q1", plan=_plan())

    assert run.status == AgentRunStatus.DRAFT.value
    assert run.plan_hash == compute_plan_hash(_plan())
    assert run.plan_json == _plan()
    assert run.created_at is not None
    assert run.started_at is None


def test_get_run_cross_user_not_found(db_session: Session) -> None:
    owner = _make_user(db_session, "owner")
    intruder = _make_user(db_session, "intruder")
    repo = AgentRunRepository(db_session)
    run = repo.create_run(user_id=owner.id, research_question="FRA85TEST q", plan=_plan())

    # Owner sees it; intruder gets NotFound (no existence leakage).
    assert repo.get_run(run.id, owner.id).id == run.id
    with pytest.raises(AgentRunNotFoundError):
        repo.get_run(run.id, intruder.id)


# ---------------------------------------------------------------------------
# transition_run: lifecycle, timestamps, illegal jumps, terminal lock
# ---------------------------------------------------------------------------


def test_run_full_lifecycle_timestamps(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = repo.create_run(user_id=user.id, research_question="FRA85TEST life", plan=_plan())

    repo.transition_run(run.id, user.id, AgentRunStatus.VALIDATED)
    repo.transition_run(run.id, user.id, AgentRunStatus.QUEUED)
    repo.transition_run(run.id, user.id, AgentRunStatus.RUNNING)
    running = repo.get_run(run.id, user.id)
    assert running.status == AgentRunStatus.RUNNING.value
    assert running.started_at is not None

    repo.transition_run(run.id, user.id, AgentRunStatus.SUCCEEDED, synthesis={"answer": "yes"})
    done = repo.get_run(run.id, user.id)
    assert done.status == AgentRunStatus.SUCCEEDED.value
    assert done.completed_at is not None
    assert done.synthesis_json == {"answer": "yes"}


def test_run_failed_stores_error_summary(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST fail")
    repo.transition_run(run.id, user.id, AgentRunStatus.VALIDATED)
    repo.transition_run(run.id, user.id, AgentRunStatus.QUEUED)
    repo.transition_run(run.id, user.id, AgentRunStatus.RUNNING)
    repo.transition_run(run.id, user.id, AgentRunStatus.FAILED, error_summary="backtest crashed")
    failed = repo.get_run(run.id, user.id)
    assert failed.status == AgentRunStatus.FAILED.value
    assert failed.completed_at is not None
    assert failed.error_summary == "backtest crashed"


def test_run_illegal_transition_raises(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST illegal")
    # draft → running is illegal (must go through validated → queued → running).
    with pytest.raises(IllegalStateTransitionError):
        repo.transition_run(run.id, user.id, AgentRunStatus.RUNNING)


def test_run_terminal_irreversible(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST terminal")
    repo.transition_run(run.id, user.id, AgentRunStatus.CANCELED)
    with pytest.raises(IllegalStateTransitionError):
        repo.transition_run(run.id, user.id, AgentRunStatus.RUNNING)


def test_run_cancel_from_running(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST cancel")
    repo.transition_run(run.id, user.id, AgentRunStatus.VALIDATED)
    repo.transition_run(run.id, user.id, AgentRunStatus.QUEUED)
    repo.transition_run(run.id, user.id, AgentRunStatus.RUNNING)
    repo.transition_run(run.id, user.id, AgentRunStatus.CANCELED)
    canceled = repo.get_run(run.id, user.id)
    assert canceled.status == AgentRunStatus.CANCELED.value
    assert canceled.canceled_at is not None


def test_transition_run_cross_user_not_found(db_session: Session) -> None:
    owner = _make_user(db_session, "owner")
    intruder = _make_user(db_session, "intruder")
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, owner, "FRA85TEST cross")
    with pytest.raises(AgentRunNotFoundError):
        repo.transition_run(run.id, intruder.id, AgentRunStatus.VALIDATED)


def test_run_backtest_link(db_session: Session) -> None:
    user = _make_user(db_session)
    bt = BacktestRun(
        user_id=user.id,
        name="FRA85TEST-bt",
        strategy_type="buy_hold",
        config_json={},
        start_date=date(2022, 1, 1),
        end_date=date(2023, 1, 1),
        price_field="adjusted",
    )
    db_session.add(bt)
    db_session.commit()
    db_session.refresh(bt)

    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST bt-link")
    repo.transition_run(run.id, user.id, AgentRunStatus.VALIDATED)
    repo.transition_run(run.id, user.id, AgentRunStatus.QUEUED)
    repo.transition_run(run.id, user.id, AgentRunStatus.RUNNING)
    repo.transition_run(run.id, user.id, AgentRunStatus.SUCCEEDED, backtest_run_id=bt.id)
    done = repo.get_run(run.id, user.id)
    assert done.backtest_run_id == bt.id


# ---------------------------------------------------------------------------
# append_step / transition_step: sequence, lifecycle, ownership
# ---------------------------------------------------------------------------


def test_append_step_and_transition(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST step")
    s1 = repo.append_step(run.id, user.id, sequence=0, agent_role="data_agent", kind="fetch_ohlcv")
    assert s1.status == AgentStepStatus.QUEUED.value
    assert s1.sequence == 0

    repo.transition_step(s1.id, user.id, AgentStepStatus.RUNNING)
    repo.transition_step(s1.id, user.id, AgentStepStatus.SUCCEEDED)
    done = repo.list_steps(run.id, user.id)[0]
    assert done.status == AgentStepStatus.SUCCEEDED.value
    assert done.finished_at is not None
    assert done.duration_ms is not None and done.duration_ms >= 0


def test_append_step_sequence_unique(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST seq")
    repo.append_step(run.id, user.id, sequence=0, agent_role="data_agent", kind="a")
    with pytest.raises(IntegrityError):
        repo.append_step(run.id, user.id, sequence=0, agent_role="data_agent", kind="b")
    db_session.rollback()


def test_append_step_cross_user_not_found(db_session: Session) -> None:
    owner = _make_user(db_session, "owner")
    intruder = _make_user(db_session, "intruder")
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, owner, "FRA85TEST step-cross")
    with pytest.raises(AgentRunNotFoundError):
        repo.append_step(run.id, intruder.id, sequence=0, agent_role="data_agent", kind="x")


def test_transition_step_illegal(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST step-illegal")
    step = repo.append_step(run.id, user.id, sequence=0, agent_role="data_agent", kind="x")
    repo.transition_step(step.id, user.id, AgentStepStatus.RUNNING)
    repo.transition_step(step.id, user.id, AgentStepStatus.SUCCEEDED)
    with pytest.raises(IllegalStateTransitionError):
        repo.transition_step(step.id, user.id, AgentStepStatus.RUNNING)


# ---------------------------------------------------------------------------
# append_tool_call / transition_tool_call: idempotency, sanitizer, ownership
# ---------------------------------------------------------------------------


def test_tool_call_idempotency_blocks_duplicate(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST idem")
    step = repo.append_step(run.id, user.id, sequence=0, agent_role="data_agent", kind="x")
    repo.append_tool_call(
        step.id, user.id, tool_name="sync_ohlcv", idempotency_key="sync-AAPL-2024"
    )
    with pytest.raises(DuplicateToolCallError):
        repo.append_tool_call(
            step.id,
            user.id,
            tool_name="sync_ohlcv",
            idempotency_key="sync-AAPL-2024",
        )


def test_tool_call_no_key_allows_multiple(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST nokey")
    step = repo.append_step(run.id, user.id, sequence=0, agent_role="risk_agent", kind="x")
    # Read-only tools (no idempotency_key) may appear multiple times.
    c1 = repo.append_tool_call(step.id, user.id, tool_name="run_risk_checks")
    c2 = repo.append_tool_call(step.id, user.id, tool_name="run_risk_checks")
    assert c1.id != c2.id


def test_tool_call_args_sanitized(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST sanitize-args")
    step = repo.append_step(run.id, user.id, sequence=0, agent_role="data_agent", kind="x")
    call = repo.append_tool_call(
        step.id,
        user.id,
        tool_name="sync_ohlcv",
        args={"api_key": "sk-secret", "symbol": "AAPL"},
    )
    assert call.args_json == {"api_key": REDACTED, "symbol": "AAPL"}


def test_tool_call_result_sanitized(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST sanitize-result")
    step = repo.append_step(run.id, user.id, sequence=0, agent_role="data_agent", kind="x")
    call = repo.append_tool_call(step.id, user.id, tool_name="sync_ohlcv")
    repo.transition_tool_call(call.id, user.id, AgentStepStatus.RUNNING)
    repo.transition_tool_call(
        call.id,
        user.id,
        AgentStepStatus.SUCCEEDED,
        result={"data": [1, 2], "token": "leaked"},
        evidence_refs=[{"type": "ohlcv", "rows": 2}],
    )
    done = repo.list_tool_calls(step.id, user.id)[0]
    assert done.status == AgentStepStatus.SUCCEEDED.value
    assert done.result_json == {"data": [1, 2], "token": REDACTED}
    assert done.evidence_refs == [{"type": "ohlcv", "rows": 2}]


def test_tool_call_failed_records_error(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST tc-fail")
    step = repo.append_step(run.id, user.id, sequence=0, agent_role="backtest_agent", kind="x")
    call = repo.append_tool_call(step.id, user.id, tool_name="run_backtest")
    repo.transition_tool_call(call.id, user.id, AgentStepStatus.RUNNING)
    repo.transition_tool_call(
        call.id,
        user.id,
        AgentStepStatus.FAILED,
        error="timeout",
        error_code="E_TIMEOUT",
    )
    done = repo.list_tool_calls(step.id, user.id)[0]
    assert done.status == AgentStepStatus.FAILED.value
    assert done.error == "timeout"
    assert done.error_code == "E_TIMEOUT"


# ---------------------------------------------------------------------------
# list_*: ordering, user scoping
# ---------------------------------------------------------------------------


def test_list_runs_user_scoped(db_session: Session) -> None:
    u1 = _make_user(db_session, "u1")
    u2 = _make_user(db_session, "u2")
    repo = AgentRunRepository(db_session)
    _make_run(repo, u1, "FRA85TEST u1-a")
    _make_run(repo, u1, "FRA85TEST u1-b")
    _make_run(repo, u2, "FRA85TEST u2-a")
    assert len(repo.list_runs(u1.id)) == 2
    assert len(repo.list_runs(u2.id)) == 1


def test_list_steps_ordered_by_sequence(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST order")
    repo.append_step(run.id, user.id, sequence=2, agent_role="risk_agent", kind="c")
    repo.append_step(run.id, user.id, sequence=0, agent_role="data_agent", kind="a")
    repo.append_step(run.id, user.id, sequence=1, agent_role="factor_agent", kind="b")
    steps = repo.list_steps(run.id, user.id)
    assert [s.sequence for s in steps] == [0, 1, 2]


# ---------------------------------------------------------------------------
# partial completion: step1 ok, step2 fails, run marks failed
# ---------------------------------------------------------------------------


def test_partial_completion_preserves_evidence(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AgentRunRepository(db_session)
    run = _make_run(repo, user, "FRA85TEST partial")

    # Advance the run to running.
    repo.transition_run(run.id, user.id, AgentRunStatus.VALIDATED)
    repo.transition_run(run.id, user.id, AgentRunStatus.QUEUED)
    repo.transition_run(run.id, user.id, AgentRunStatus.RUNNING)

    # Step 1 succeeds with evidence.
    s1 = repo.append_step(run.id, user.id, sequence=0, agent_role="data_agent", kind="fetch")
    repo.transition_step(s1.id, user.id, AgentStepStatus.RUNNING)
    repo.transition_step(s1.id, user.id, AgentStepStatus.SUCCEEDED, output_summary={"rows": 500})

    # Step 2 fails.
    s2 = repo.append_step(run.id, user.id, sequence=1, agent_role="backtest_agent", kind="run")
    repo.transition_step(s2.id, user.id, AgentStepStatus.RUNNING)
    repo.transition_step(s2.id, user.id, AgentStepStatus.FAILED, error="no data")

    # Run is marked failed, but step 1's evidence survives.
    repo.transition_run(run.id, user.id, AgentRunStatus.FAILED, error_summary="step 2 failed")
    steps = repo.list_steps(run.id, user.id)
    assert steps[0].status == AgentStepStatus.SUCCEEDED.value
    assert steps[0].output_summary == {"rows": 500}
    assert steps[1].status == AgentStepStatus.FAILED.value
    assert steps[1].error == "no data"
    final = repo.get_run(run.id, user.id)
    assert final.status == AgentRunStatus.FAILED.value


# ---------------------------------------------------------------------------
# DB CHECK constraints: reject illegal status / role / tool values
# ---------------------------------------------------------------------------


def test_db_rejects_illegal_run_status(db_session: Session) -> None:
    """CHECK constraint rejects a status outside the FRA-84 allowlist."""
    from app.models.agent import ResearchRun

    user = _make_user(db_session)
    run = ResearchRun(
        user_id=user.id,
        research_question="FRA85TEST bad-status",
        plan_schema_version="1.0",
        plan_json={},
        plan_hash="x" * 64,
        status="bogus",  # not in the allowlist
    )
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_db_rejects_illegal_tool_name(db_session: Session) -> None:
    """CHECK constraint rejects a tool_name outside the FRA-84 catalog."""
    from app.models.agent import AgentToolCall, ResearchRun, ResearchStep

    user = _make_user(db_session)
    run = ResearchRun(
        user_id=user.id,
        research_question="FRA85TEST bad-tool",
        plan_schema_version="1.0",
        plan_json={},
        plan_hash="y" * 64,
    )
    db_session.add(run)
    db_session.commit()
    step = ResearchStep(run_id=run.id, sequence=0, agent_role="data_agent", kind="x")
    db_session.add(step)
    db_session.commit()
    call = AgentToolCall(step_id=step.id, tool_name="eval_shell")  # not in catalog
    db_session.add(call)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_migration_roundtrip_does_not_break_existing_tables(db_session: Session) -> None:
    """Existing tables (assets/users) remain queryable after the new migration."""
    user = _make_user(db_session, "rt")
    asset = _make_asset(db_session, "FRA85TEST-RT")
    assert user.id is not None
    assert asset.id is not None
