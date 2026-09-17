"""Regression tests for durable dispatch and nonblocking, bounded worker jobs."""
import asyncio
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arq import Retry
from fastapi import BackgroundTasks, HTTPException

from app.core.config import settings
from app.services.jobs import JobDispatchError, enqueue_or_run
from app import worker


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _request(pool):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq_pool=pool)))


@pytest.mark.anyio
async def test_configured_queue_never_falls_back_when_pool_missing(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379")
    background = BackgroundTasks()
    with pytest.raises(JobDispatchError) as caught:
        await enqueue_or_run(_request(None), background, "job", lambda: None)
    assert caught.value.status_code == 503
    assert caught.value.may_have_enqueued is False
    assert caught.value.headers["Retry-After"]
    assert background.tasks == []


@pytest.mark.anyio
async def test_enqueue_timeout_is_explicitly_ambiguous():
    pool = SimpleNamespace(enqueue_job=AsyncMock(side_effect=TimeoutError("reply lost")))
    background = BackgroundTasks()
    with pytest.raises(JobDispatchError) as caught:
        await enqueue_or_run(_request(pool), background, "job", lambda: None)
    assert caught.value.may_have_enqueued is True
    assert background.tasks == []


@pytest.mark.anyio
async def test_duplicate_durable_job_is_success_and_id_stays_out_of_sync_args():
    pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=None))
    background = BackgroundTasks()
    assert await enqueue_or_run(_request(pool), background, "job", lambda: None, 7, job_id="doc:7") == "arq"
    pool.enqueue_job.assert_awaited_once_with("job", 7, _job_id="doc:7")
    assert background.tasks == []


@pytest.mark.anyio
async def test_local_job_id_is_not_passed_to_callable(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "")
    background = BackgroundTasks()
    received = []
    await enqueue_or_run(_request(None), background, "job", received.append, 7, job_id="doc:7")
    await background()
    assert received == [7]


@pytest.mark.anyio
async def test_worker_process_is_responsive_and_reaped_on_repeated_cancel(tmp_path, monkeypatch):
    started = tmp_path / "started"
    children = []
    original = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        child = await original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    command = (
        "import signal,time;from pathlib import Path;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        f"Path({str(started)!r}).write_text('ready');time.sleep(30)"
    )
    task = asyncio.create_task(worker._run_command(sys.executable, "-c", command))
    try:
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert started.exists(), "child never started"
        before = time.monotonic()
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert time.monotonic() - before < 5
        assert children[0].returncode is not None
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.anyio
async def test_worker_process_preserves_exit_status():
    assert await worker._run_command(sys.executable, "-c", "raise SystemExit(75)") == 75


@pytest.mark.anyio
async def test_child_hard_deadline_terminates_without_parent_cancellation():
    api_dir = str(Path(worker.__file__).resolve().parents[1])
    code = (
        f"import sys,time;sys.path.insert(0,{api_dir!r});"
        "from app.job_runner import _install_process_guards;"
        "_install_process_guards(None,time.monotonic()+0.2);time.sleep(30)"
    )
    before = time.monotonic()
    result = await asyncio.wait_for(worker._run_command(sys.executable, "-c", code), timeout=5)
    assert result != 0
    assert time.monotonic() - before < 5


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux kernel parent-death guard")
@pytest.mark.anyio
async def test_child_dies_when_worker_parent_is_killed(tmp_path):
    api_dir = str(Path(worker.__file__).resolve().parents[1])
    marker = tmp_path / "child-pid"
    child_code = (
        f"import sys,os,time;sys.path.insert(0,{api_dir!r});"
        "from pathlib import Path;from app.job_runner import _install_process_guards;"
        "_install_process_guards(PARENT_PID,time.monotonic()+10);"
        f"Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(30)"
    )
    parent_code = (
        "import subprocess,sys,os,time;"
        f"code={child_code!r}.replace('PARENT_PID',str(os.getpid()));"
        "subprocess.Popen([sys.executable,'-c',code],start_new_session=True);time.sleep(30)"
    )
    task = asyncio.create_task(worker._run_command(sys.executable, "-c", parent_code))
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert marker.exists()
        pid = int(marker.read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            stat = Path(f"/proc/{pid}/stat")
            if not stat.exists() or stat.read_text().split()[2] == "Z":
                break  # A zombie has exited and cannot publish database writes.
            await asyncio.sleep(0.01)
        else:
            pytest.fail("job child survived the death of its Arq parent")
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.anyio
async def test_transient_ingestion_retry_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "WORKER_MAX_TRIES", 3)
    monkeypatch.setattr(worker, "_run_command", AsyncMock(return_value=75))
    with pytest.raises(Retry):
        await worker.run_ingestion_for_document({"job_try": 1}, 4, 1)
    with pytest.raises(worker.JobProcessError):
        await worker.run_ingestion_for_document({"job_try": 3}, 4, 1)


@pytest.mark.anyio
async def test_permanent_ingestion_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(worker, "_run_command", AsyncMock(return_value=1))
    with pytest.raises(worker.JobProcessError):
        await worker.run_ingestion_for_document({"job_try": 1}, 4, 1)


def test_job_runner_classifies_failures(monkeypatch):
    from app.job_runner import main

    def transient(*args):
        raise TimeoutError("embedding timeout")

    monkeypatch.setattr(worker, "_run_ingestion", transient)
    monkeypatch.setattr(sys, "argv", ["runner", "ingestion", "4", "1"])
    assert main() == 75

    def permanent(*args):
        raise ValueError("corrupt document")

    monkeypatch.setattr(worker, "_run_ingestion", permanent)
    assert main() == 1


@pytest.mark.anyio
async def test_ingestion_job_runner_uses_its_own_session_and_import_paths(db, test_deal, tmp_path, monkeypatch):
    from app.models.document import Document, DocumentStatus

    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(Path.cwd() / "test_diligenx.db"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("BETA_MODE", "false")
    source = tmp_path / "job.txt"
    source.write_text("The agreement renews for twelve months unless terminated.", encoding="utf-8")
    document = Document(
        deal_id=test_deal.id, filename=source.name, file_path=source.name,
        mime_type="text/plain", file_size=source.stat().st_size, status=DocumentStatus.pending,
    )
    db.add(document)
    db.commit()
    document_id, user_id = document.id, test_deal.workspace.owner_id
    db.commit()  # Release the test session before the independent process writes.
    await worker.run_ingestion_for_document({"job_try": 1}, document_id, user_id)
    db.refresh(document)
    assert document.status == DocumentStatus.processed
    assert "twelve months" in document.raw_text


@pytest.mark.parametrize("status, expected", [(400, False), (401, False), (413, False), (429, True), (500, True), (503, True)])
def test_provider_retry_classification(status, expected):
    error = RuntimeError("provider failure")
    error.status_code = status
    assert worker._is_transient(error) is expected
