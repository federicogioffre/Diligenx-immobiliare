"""Interrupted workers preserve completed analysis and release only their admission."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import sessionmaker

from app import worker
from app.db import session as session_module
from app.models.agent_finding import AgentFinding
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.deal import DealStatus
from app.models.red_flag import Severity
from app.services.analysis_failure import mark_analysis_failed


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def analysis_case(db, test_deal, test_user, monkeypatch):
    admission = datetime.now(timezone.utc) - timedelta(minutes=3)
    test_deal.status = DealStatus.analyzing
    test_deal.updated_at = admission
    completed = AgentRun(deal_id=test_deal.id, agent_name="contract_analysis",
                         status=AgentRunStatus.completed, started_at=admission,
                         completed_at=admission + timedelta(seconds=10))
    running = AgentRun(deal_id=test_deal.id, agent_name="financial_analysis",
                       status=AgentRunStatus.running, started_at=admission + timedelta(minutes=1))
    historical = AgentRun(deal_id=test_deal.id, agent_name="old_unfinished_stage",
                          status=AgentRunStatus.running, started_at=admission - timedelta(days=1))
    finding = AgentFinding(deal_id=test_deal.id, agent_name="contract_analysis",
                           category="contract", title="Preserved result", description="Existing output",
                           severity=Severity.medium)
    db.add_all([completed, running, historical, finding])
    db.commit()
    ids = SimpleNamespace(deal=test_deal.id, user=test_user.id, completed=completed.id,
                          running=running.id, historical=historical.id, finding=finding.id,
                          admission=test_deal.updated_at)
    db.commit()  # Independent worker sessions must be free to write.
    monkeypatch.setattr(session_module, "SessionLocal", sessionmaker(bind=db.bind))
    return ids


def assert_failed_and_preserved(db, case):
    from app.models.deal import Deal
    db.expire_all()
    assert db.get(Deal, case.deal).status == DealStatus.draft
    failed = db.get(AgentRun, case.running)
    assert failed.status == AgentRunStatus.failed
    assert failed.completed_at is not None
    assert failed.error_message
    assert db.get(AgentRun, case.completed).status == AgentRunStatus.completed
    assert db.get(AgentRun, case.historical).status == AgentRunStatus.running
    assert db.get(AgentFinding, case.finding).title == "Preserved result"


def test_failure_helper_changes_only_current_running_stage(db, analysis_case):
    case = analysis_case
    assert mark_analysis_failed(db, case.deal, case.user, "Worker stopped",
                                expected_admission=case.admission,
                                invocation_started_at=datetime.now(timezone.utc))
    db.commit()
    assert_failed_and_preserved(db, case)


@pytest.mark.parametrize("guard", ["wrong_tenant", "new_admission", "completed", "future_admission"])
def test_cleanup_does_not_touch_another_tenant_or_newer_run(db, analysis_case, guard):
    from app.models.deal import Deal
    case = analysis_case
    deal = db.get(Deal, case.deal)
    user = case.user
    if guard == "wrong_tenant":
        user += 1000
    elif guard in ("new_admission", "future_admission"):
        deal.updated_at = datetime.now(timezone.utc) + timedelta(seconds=10)
    else:
        deal.status = DealStatus.reviewed
    db.commit()
    expected = deal.updated_at if guard == "future_admission" else case.admission
    assert not mark_analysis_failed(db, case.deal, user, "Must not overwrite",
                                    expected_admission=expected,
                                    invocation_started_at=datetime.now(timezone.utc))
    db.commit()
    assert db.get(AgentRun, case.running).status == AgentRunStatus.running
    assert db.get(AgentRun, case.completed).status == AgentRunStatus.completed
    assert db.get(AgentFinding, case.finding).title == "Preserved result"
    assert deal.status == (DealStatus.reviewed if guard == "completed" else DealStatus.analyzing)


@pytest.mark.anyio
@pytest.mark.parametrize("function", [worker.run_pipeline_for_deal, worker.run_resume_pipeline_for_deal])
async def test_nonzero_exit_reconciles_in_parent_without_retry(db, analysis_case, monkeypatch, function):
    case = analysis_case
    monkeypatch.setattr(worker, "_run_command", AsyncMock(return_value=-9))
    with pytest.raises(worker.JobProcessError, match="exit -9"):
        await function({}, case.deal, case.user)
    assert_failed_and_preserved(db, case)


@pytest.mark.anyio
async def test_spawn_failure_reconciles_the_admitted_analysis(db, analysis_case, monkeypatch):
    case = analysis_case
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(side_effect=OSError("spawn failed")))
    with pytest.raises(OSError, match="spawn failed"):
        await worker.run_pipeline_for_deal({}, case.deal, case.user)
    assert_failed_and_preserved(db, case)


@pytest.mark.anyio
async def test_cancel_cleanup_waits_for_child_termination_and_does_not_retry(db, analysis_case, monkeypatch):
    case = analysis_case
    started, stopped = asyncio.Event(), asyncio.Event()
    process = SimpleNamespace(returncode=None)

    async def wait():
        started.set()
        await stopped.wait()
        return process.returncode

    async def stop(child):
        assert child is process
        await asyncio.sleep(0.02)
        child.returncode = -9
        stopped.set()

    process.wait = wait
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(worker, "_stop_process", stop)
    original = worker._persist_analysis_failure

    def cleanup(*args):
        assert process.returncode == -9, "DB cleanup ran while the child was still alive"
        original(*args)

    monkeypatch.setattr(worker, "_persist_analysis_failure", cleanup)
    task = asyncio.create_task(worker.run_pipeline_for_deal({}, case.deal, case.user))
    await asyncio.wait_for(started.wait(), timeout=3)
    task.cancel()
    await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(worker.JobProcessError, match="cancelled"):
        await task
    assert_failed_and_preserved(db, case)


@pytest.mark.anyio
async def test_unconfirmed_termination_keeps_admission_locked(db, analysis_case, monkeypatch):
    from app.models.deal import Deal
    case = analysis_case
    monkeypatch.setattr(worker, "_run_command", AsyncMock(side_effect=worker.JobTerminationError("still alive")))
    with pytest.raises(worker.JobTerminationError):
        await worker.run_pipeline_for_deal({}, case.deal, case.user)
    db.expire_all()
    assert db.get(Deal, case.deal).status == DealStatus.analyzing
    assert db.get(AgentRun, case.running).status == AgentRunStatus.running


@pytest.mark.anyio
async def test_cancel_during_admission_capture_never_spawns_or_retries(db, analysis_case, monkeypatch):
    import threading

    case = analysis_case
    entered, release = threading.Event(), threading.Event()
    original = worker._capture_analysis_admission

    def capture(*args):
        entered.set()
        assert release.wait(timeout=3)
        return original(*args)

    run = AsyncMock(return_value=0)
    monkeypatch.setattr(worker, "_capture_analysis_admission", capture)
    monkeypatch.setattr(worker, "_run_command", run)
    task = asyncio.create_task(worker.run_pipeline_for_deal({}, case.deal, case.user))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        release.set()
    with pytest.raises(worker.JobProcessError, match="cancelled before spawn"):
        await task
    run.assert_not_awaited()
    assert_failed_and_preserved(db, case)


@pytest.mark.anyio
async def test_wrong_tenant_cannot_spawn_analysis_or_change_status(db, analysis_case, monkeypatch):
    from app.models.deal import Deal
    case = analysis_case
    run = AsyncMock(return_value=0)
    monkeypatch.setattr(worker, "_run_command", run)
    with pytest.raises(worker.JobProcessError, match="admission is no longer active"):
        await worker.run_pipeline_for_deal({}, case.deal, case.user + 1000)
    run.assert_not_awaited()
    db.expire_all()
    assert db.get(Deal, case.deal).status == DealStatus.analyzing


@pytest.mark.anyio
async def test_late_parent_failure_cannot_downgrade_a_replacement_admission(db, analysis_case, monkeypatch):
    from app.models.deal import Deal
    case = analysis_case

    async def fail_after_replacement(*args):
        with session_module.SessionLocal() as fresh:
            deal = fresh.get(Deal, case.deal)
            deal.updated_at = datetime.now(timezone.utc) + timedelta(seconds=1)
            fresh.commit()
        return -9

    monkeypatch.setattr(worker, "_run_command", fail_after_replacement)
    with pytest.raises(worker.JobProcessError):
        await worker.run_pipeline_for_deal({}, case.deal, case.user)
    db.expire_all()
    assert db.get(Deal, case.deal).status == DealStatus.analyzing
    assert db.get(AgentRun, case.running).status == AgentRunStatus.running


def test_resume_child_routes_to_resuming_orchestrator(db, analysis_case, monkeypatch):
    import sys
    from app.job_runner import main
    from packages.agents import orchestrator

    called = []
    monkeypatch.setattr(orchestrator, "run_deal_analysis_pipeline",
                        lambda deal_id, session, **kwargs: called.append((deal_id, kwargs)))
    monkeypatch.setattr(sys, "argv", ["runner", "resume", str(analysis_case.deal), str(analysis_case.user)])
    assert main() == 0
    assert called == [(analysis_case.deal, {"resume": True})]
    assert worker.run_resume_pipeline_for_deal in worker.WorkerSettings.functions


def test_analysis_transient_failure_does_not_emit_ingestion_retry_code(monkeypatch):
    import sys
    from app.job_runner import main

    def fail(*args):
        raise TimeoutError("provider timeout")

    monkeypatch.setattr(worker, "_run_pipeline", fail)
    monkeypatch.setattr(sys, "argv", ["runner", "analysis", "4", "1"])
    assert main() == 1
