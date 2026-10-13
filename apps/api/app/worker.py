"""Arq jobs run in a dedicated subprocess, owning its database sessions.

Cancellation terminates and reaps the child before Arq can release/retry the
job. Unlike a thread, a timed-out subprocess cannot continue publishing results
after the queue's in-progress lease expires.
"""
import asyncio
from datetime import datetime, timezone
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


class JobTerminationError(RuntimeError):
    """The child could not be proven inactive; database cleanup is unsafe."""


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
        await _reap_process(process)
        raise
    except Exception:
        if process is not None and process.returncode is None:
            await _reap_process(process)
        raise


async def _reap_process(process: asyncio.subprocess.Process) -> None:
    stop = asyncio.create_task(_stop_process(process))
    while not stop.done():
        try:
            await asyncio.shield(stop)
        except asyncio.CancelledError:
            continue
        except Exception as exc:
            raise JobTerminationError("Unable to confirm analysis process termination") from exc
    try:
        stop.result()
    except Exception as exc:
        raise JobTerminationError("Unable to confirm analysis process termination") from exc


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
    _run_analysis_pipeline(deal_id, user_id, resume=False)


def _run_resume_pipeline(deal_id: int, user_id: int) -> None:
    _run_analysis_pipeline(deal_id, user_id, resume=True)


def _run_analysis_pipeline(deal_id: int, user_id: int, *, resume: bool) -> None:
    from app.db.session import SessionLocal
    from app.db.tenant_context import set_tenant_context
    from packages.agents.orchestrator import run_deal_analysis_pipeline

    db = SessionLocal()
    try:
        set_tenant_context(db, user_id)
        if resume:
            run_deal_analysis_pipeline(deal_id, db, resume=True)
        else:
            run_deal_analysis_pipeline(deal_id, db)
        # Exceptions, hard exits and cancellation are reconciled by the parent
        # after the child exits, using the same admission guard in every case.
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
        if doc is None or doc.analysis_ready:
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
    await _run_analysis_job("analysis", deal_id, user_id)


async def run_resume_pipeline_for_deal(ctx: dict[str, Any], deal_id: int, user_id: int) -> None:
    await _run_analysis_job("resume", deal_id, user_id)


def _capture_analysis_admission(deal_id: int, user_id: int) -> datetime | None:
    from app.db.session import SessionLocal
    from app.db.tenant_context import set_tenant_context
    from app.models.deal import Deal, DealStatus

    with SessionLocal() as db:
        set_tenant_context(db, user_id)
        deal = db.query(Deal).filter(
            Deal.id == deal_id, Deal.workspace.has(owner_id=user_id),
            Deal.status == DealStatus.analyzing,
        ).first()
        return (deal.updated_at or deal.created_at) if deal is not None else None


def _persist_analysis_failure(deal_id: int, user_id: int, admission: datetime,
                              invocation_started_at: datetime, reason: str) -> None:
    from app.db.session import SessionLocal
    from app.services.analysis_failure import mark_analysis_failed

    with SessionLocal() as db:
        mark_analysis_failed(db, deal_id, user_id, reason,
                             expected_admission=admission,
                             invocation_started_at=invocation_started_at)
        db.commit()


async def _cleanup_analysis_failure(deal_id: int, user_id: int, admission: datetime,
                                    invocation_started_at: datetime, reason: str) -> None:
    # The child is already reaped. Finish the short DB transaction even if Arq
    # repeats cancellation during shutdown; never release the job beforehand.
    cleanup = asyncio.create_task(asyncio.to_thread(
        _persist_analysis_failure, deal_id, user_id, admission, invocation_started_at, reason,
    ))
    try:
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        cleanup.result()
    except Exception:
        logger.exception("Could not reconcile interrupted analysis for deal %d", deal_id)


async def _run_analysis_job(kind: str, deal_id: int, user_id: int) -> None:
    invocation_started_at = datetime.now(timezone.utc)
    capture = asyncio.create_task(asyncio.to_thread(_capture_analysis_admission, deal_id, user_id))
    try:
        admission = await asyncio.shield(capture)
    except asyncio.CancelledError:
        # Even cancellation before spawn must not cause an automatic restart.
        # Finish the read so we can safely release this specific admission.
        while not capture.done():
            try:
                await asyncio.shield(capture)
            except asyncio.CancelledError:
                continue
        admission = capture.result()
        if admission is not None:
            await _cleanup_analysis_failure(
                deal_id, user_id, admission, invocation_started_at,
                "Analisi interrotta prima dell’avvio. Le fasi completate sono state conservate.",
            )
        raise JobProcessError(f"Analysis cancelled before spawn for deal {deal_id}") from None
    if admission is None:
        raise JobProcessError(f"Analysis admission is no longer active for deal {deal_id}")
    try:
        code = await _run_command(*_job_command(kind, deal_id, user_id))
        if code:
            raise JobProcessError(f"Analysis process failed for deal {deal_id} (exit {code})")
    except JobTerminationError:
        # A possibly live child must retain the admission lock. Maintenance may
        # reconcile it later, once process/queue inactivity can be established.
        raise
    except (Exception, asyncio.CancelledError) as exc:
        reason = "Analisi interrotta o terminata oltre il tempo massimo. Le fasi completate sono state conservate."
        await _cleanup_analysis_failure(deal_id, user_id, admission, invocation_started_at, reason)
        if isinstance(exc, asyncio.CancelledError):
            # Arq retries CancelledError automatically. Analysis retries must be
            # explicit, after inspecting the checkpoint, never start from zero.
            raise JobProcessError(f"Analysis cancelled for deal {deal_id}") from None
        raise


async def run_ingestion_for_document(ctx: dict[str, Any], document_id: int, user_id: int) -> None:
    code = await _run_command(*_job_command("ingestion", document_id, user_id))
    if code == 75 and int(ctx.get("job_try", 1)) < settings.WORKER_MAX_TRIES:
        raise Retry(defer=min(10 * 2 ** (int(ctx.get("job_try", 1)) - 1), 120))
    if code:
        raise JobProcessError(f"Ingestion process failed for document {document_id} (exit {code})")


# A deploy starts API and worker together, and only the API runs the
# migrations: a worker that checks first would find the previous revision.
MIGRATION_WAIT_SECONDS = 300
MIGRATION_POLL_SECONDS = 5


async def _startup(ctx: dict[str, Any]) -> None:
    from app.core.runtime_validation import (
        PendingMigrationsError, validate_beta_configuration, validate_beta_database,
    )

    validate_beta_configuration()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + MIGRATION_WAIT_SECONDS
    while True:
        try:
            await asyncio.to_thread(validate_beta_database)
            return
        except PendingMigrationsError:
            if loop.time() >= deadline:
                raise
            logger.warning("Database not at the migration head yet; waiting for the API to migrate")
            await asyncio.sleep(MIGRATION_POLL_SECONDS)


class WorkerSettings:
    on_startup = _startup
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL) if settings.REDIS_URL else None
    functions = [run_pipeline_for_deal, run_resume_pipeline_for_deal, run_ingestion_for_document]
    max_jobs = settings.WORKER_MAX_JOBS
    job_timeout = settings.WORKER_JOB_TIMEOUT_SECONDS
    max_tries = settings.WORKER_MAX_TRIES
    keep_result = 0
    health_check_interval = 15
