"""Arq jobs run in a dedicated subprocess, owning its database sessions.

Cancellation terminates and reaps the child before Arq can release/retry the
job. Unlike a thread, a timed-out subprocess cannot continue publishing results
after the queue's in-progress lease expires.
"""
import asyncio
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any

import httpx
from arq import Retry
from arq.connections import RedisSettings
from sqlalchemy.exc import OperationalError

from app.core.config import settings

logger = logging.getLogger(__name__)


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except asyncio.TimeoutError:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        # SIGKILL/TerminateProcess makes the child unable to commit. Reap it
        # before releasing job ownership, rather than abandoning a live task.
        await process.wait()


async def _run_command(*command: str) -> int:
    options = {"start_new_session": True} if os.name == "posix" else {
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(*command, **options))
    process = None
    try:
        process = await asyncio.shield(spawn)
        return await process.wait()
    except asyncio.CancelledError:
        # Cancellation may arrive while the OS is spawning, or repeat during
        # shutdown. Finish spawning, then terminate exactly that child.
        while process is None:
            try:
                process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                continue
        stop = asyncio.create_task(_stop_process(process))
        while not stop.done():
            try:
                await asyncio.shield(stop)
            except asyncio.CancelledError:
                continue
        stop.result()
        raise


def _job_command(kind: str, entity_id: int, user_id: int) -> tuple[str, ...]:
    # -c sets import paths explicitly, independently of the deployment cwd;
    # inherited cwd/env preserve storage configuration and runtime credentials.
    api_dir = str(Path(__file__).resolve().parents[1])
    repo_dir = str(Path(__file__).resolve().parents[3])
    bootstrap = (
        f"import sys;sys.path[:0]=[{api_dir!r},{repo_dir!r}];"
        "from app.job_runner import main;sys.exit(main())"
    )
    # Use an absolute monotonic deadline so slow imports/spawn cannot extend
    # the child's life past Arq's in-progress lease. Leave time for reaping.
    deadline = time.monotonic() + max(0.1, settings.WORKER_JOB_TIMEOUT_SECONDS - 5)
    return (
        sys.executable, "-c", bootstrap, kind, str(entity_id), str(user_id),
        "--parent-pid", str(os.getpid()), "--deadline", str(deadline),
    )


class JobProcessError(RuntimeError):
    pass


def _run_pipeline(deal_id: int, user_id: int) -> None:
    from app.db.session import SessionLocal
    from app.db.tenant_context import set_tenant_context
    from app.models.deal import Deal, DealStatus
    from packages.agents.orchestrator import run_deal_analysis_pipeline

    db = SessionLocal()
    try:
        set_tenant_context(db, user_id)
        run_deal_analysis_pipeline(deal_id, db)
    except Exception:
        db.rollback()
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal is not None:
            deal.status = DealStatus.draft
            db.commit()
        raise
    finally:
        db.close()


def _run_ingestion(document_id: int, user_id: int) -> None:
    from app.db.session import SessionLocal
    from app.db.tenant_context import set_tenant_context
    from app.models.document import Document, DocumentStatus
    from packages.parsing.ingestion_pipeline import process_document

    db = SessionLocal()
    try:
        set_tenant_context(db, user_id)
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc is None or doc.status == DocumentStatus.processed:
            return
        process_document(document_id, db)
    except Exception:
        db.rollback()
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc is not None:
            doc.status = DocumentStatus.failed
            db.commit()
        raise
    finally:
        db.close()


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError, httpx.TransportError, OperationalError)):
        return True
    # SDKs wrap httpx errors in APIConnectionError/APITimeoutError.
    if isinstance(exc.__cause__, (ConnectionError, TimeoutError, httpx.TransportError)):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status in (408, 429) or status >= 500)


async def run_pipeline_for_deal(ctx: dict[str, Any], deal_id: int, user_id: int) -> None:
    code = await _run_command(*_job_command("analysis", deal_id, user_id))
    if code:
        raise JobProcessError(f"Analysis process failed for deal {deal_id} (exit {code})")


async def run_ingestion_for_document(ctx: dict[str, Any], document_id: int, user_id: int) -> None:
    code = await _run_command(*_job_command("ingestion", document_id, user_id))
    if code == 75 and int(ctx.get("job_try", 1)) < settings.WORKER_MAX_TRIES:
        raise Retry(defer=min(10 * 2 ** (int(ctx.get("job_try", 1)) - 1), 120))
    if code:
        raise JobProcessError(f"Ingestion process failed for document {document_id} (exit {code})")


async def _startup(ctx: dict[str, Any]) -> None:
    from app.core.runtime_validation import validate_beta_configuration, validate_beta_database

    validate_beta_configuration()
    await asyncio.to_thread(validate_beta_database)


class WorkerSettings:
    on_startup = _startup
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL) if settings.REDIS_URL else None
    functions = [run_pipeline_for_deal, run_ingestion_for_document]
    max_jobs = settings.WORKER_MAX_JOBS
    job_timeout = settings.WORKER_JOB_TIMEOUT_SECONDS
    max_tries = settings.WORKER_MAX_TRIES
    keep_result = 0
    health_check_interval = 15
