"""Dispatch durable jobs; the in-process path is for explicit local mode only."""
import logging
import asyncio
from typing import Any, Callable

from fastapi import BackgroundTasks, HTTPException, Request

from app.core.config import settings

logger = logging.getLogger(__name__)


class JobDispatchError(HTTPException):
    """An uncertain Redis response must not release an active analysis claim."""

    def __init__(self, detail: str, *, may_have_enqueued: bool):
        super().__init__(status_code=503, detail=detail, headers={"Retry-After": "10"})
        self.may_have_enqueued = may_have_enqueued


async def enqueue_or_run(
    request: Request,
    background_tasks: BackgroundTasks,
    arq_function_name: str,
    sync_function: Callable[..., Any],
    *args: Any,
    job_id: str | None = None,
    **kwargs: Any,
) -> str:
    """Raise 503 if durable dispatch is unavailable.

    A stable job_id prevents duplicate in-flight Arq jobs. Arq returning None
    means this ID is already queued/running, a successful dispatch.
    WorkerSettings.keep_result=0 permits later intentional re-runs of the ID.
    Queue options never reach the synchronous development fallback.
    """
    pool = getattr(request.app.state, "arq_pool", None)
    if pool is not None:
        try:
            options = {"_job_id": job_id} if job_id is not None else {}
            await asyncio.wait_for(
                pool.enqueue_job(arq_function_name, *args, **options, **kwargs), timeout=10,
            )
            return "arq"
        except Exception as exc:
            logger.exception("Durable dispatch failed for %s", arq_function_name)
            raise JobDispatchError(
                detail="Elaborazione temporaneamente non disponibile. Riprovare il caricamento o l'analisi.",
                may_have_enqueued=True,
            ) from exc
    if settings.REDIS_URL:
        raise JobDispatchError(
            detail="Coda di elaborazione non disponibile. Riprovare tra poco.",
            may_have_enqueued=False,
        )
    background_tasks.add_task(sync_function, *args, **kwargs)
    return "background_tasks"

