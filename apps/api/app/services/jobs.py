"""Durable job queue abstraction.

Routes call :func:`enqueue_or_run` instead of ``background_tasks.add_task``
directly. When ``REDIS_URL`` is configured at startup we hold an Arq pool
on ``app.state.arq_pool``; ``enqueue_or_run`` then schedules the job there
so it survives worker restarts. When the pool is not present (the default
in development and in tests) we fall back to the existing in-process
``BackgroundTasks`` behaviour, preserving the pre-Arq contract.

The two callables wired through this helper today are
:func:`packages.agents.orchestrator.run_deal_analysis_pipeline` (via
``run_pipeline_for_deal``) and :func:`packages.parsing.ingestion_pipeline.
process_document` (via ``run_ingestion_for_document``); see ``app.worker``
for the Arq task definitions that the worker process consumes.
"""
import logging
from typing import Any, Callable

from fastapi import BackgroundTasks, Request

logger = logging.getLogger(__name__)


async def enqueue_or_run(
    request: Request,
    background_tasks: BackgroundTasks,
    arq_function_name: str,
    sync_function: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> str:
    """Enqueue *arq_function_name* on Arq when configured, else schedule
    *sync_function* in the request's BackgroundTasks.

    Returns the string ``"arq"`` or ``"background_tasks"`` to indicate
    which path was taken (used by tests; production callers can ignore it).

    Any failure on the Arq enqueue path falls back transparently to
    BackgroundTasks — we'd rather still run the job in-process than reject
    a user request because Redis blipped.
    """
    pool = getattr(request.app.state, "arq_pool", None)
    if pool is not None:
        try:
            await pool.enqueue_job(arq_function_name, *args, **kwargs)
            logger.info(
                "Enqueued %s(args=%s, kwargs=%s) via Arq.",
                arq_function_name, args, kwargs,
            )
            return "arq"
        except Exception:
            logger.exception(
                "Arq enqueue failed for %s; falling back to BackgroundTasks.",
                arq_function_name,
            )

    background_tasks.add_task(sync_function, *args, **kwargs)
    return "background_tasks"
