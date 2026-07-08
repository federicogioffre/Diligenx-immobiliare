"""Arq worker entry point for durable background jobs.

Run alongside the API process when ``REDIS_URL`` is set:

    arq app.worker.WorkerSettings

The worker consumes jobs enqueued by ``app.services.jobs.enqueue_or_run``
from the API request handlers. Each task here is a thin async wrapper
that delegates to the same synchronous pipeline functions the in-process
``BackgroundTasks`` path already uses — there is exactly one
implementation of "process a document" and "analyse a deal", regardless
of which dispatch mechanism scheduled it.
"""
import logging
from typing import Any

from arq.connections import RedisSettings

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Task functions ────────────────────────────────────────────────────────


async def run_pipeline_for_deal(
    ctx: dict[str, Any], deal_id: int, user_id: int
) -> None:
    """Arq task: execute the multi-agent analysis pipeline for *deal_id*.

    *user_id* is the deal owner; it binds the RLS tenant context on the
    fresh session so row-level policies apply to the worker's queries.
    """
    from app.db.session import SessionLocal
    from app.db.tenant_context import set_tenant_context
    from packages.agents.orchestrator import run_deal_analysis_pipeline

    logger.info("[arq] Running analysis pipeline for deal %d", deal_id)
    db = SessionLocal()
    try:
        set_tenant_context(db, user_id)
        run_deal_analysis_pipeline(deal_id, db)
    finally:
        db.close()


async def run_ingestion_for_document(
    ctx: dict[str, Any], document_id: int, user_id: int
) -> None:
    """Arq task: extract → chunk → embed for *document_id*.

    *user_id* is the uploader; binds the RLS tenant context (see above).
    """
    from app.db.session import SessionLocal
    from app.db.tenant_context import set_tenant_context
    from app.models.document import Document, DocumentStatus
    from packages.parsing.ingestion_pipeline import process_document

    logger.info("[arq] Running ingestion for document %d", document_id)
    db = SessionLocal()
    try:
        set_tenant_context(db, user_id)
        try:
            process_document(document_id, db)
        except Exception:
            logger.exception("[arq] Ingestion failed for document %d", document_id)
            try:
                doc = db.query(Document).filter(Document.id == document_id).first()
                if doc and doc.status != DocumentStatus.failed:
                    doc.status = DocumentStatus.failed
                    db.commit()
            except Exception:
                logger.exception(
                    "[arq] Could not persist failed state for document %d", document_id,
                )
    finally:
        db.close()


# ── Worker settings ───────────────────────────────────────────────────────


class WorkerSettings:
    """Read by ``arq`` when launched as ``arq app.worker.WorkerSettings``."""

    redis_settings = (
        RedisSettings.from_dsn(settings.REDIS_URL) if settings.REDIS_URL else None
    )

    functions = [run_pipeline_for_deal, run_ingestion_for_document]

    # Modest concurrency by default — the bottleneck is the LLM provider's
    # rate limit, not local CPU. Tune via env if needed.
    max_jobs = 4

    # Each stage of the analysis pipeline can take many seconds; report
    # rendering can take longer when the model is rate-limited.
    job_timeout = 60 * 15
