"""Bounded parallel execution for per-document LLM work.

The analysis pipeline's dominant cost is sequential LLM round-trips: every
stage used to loop documents one at a time, so wall-clock grew linearly with
data-room size. The per-document calls within a stage are independent, so
they can fan out.

Contract for worker functions passed to :func:`run_llm_tasks`:

* PURE with respect to the database — a worker may call the LLM, parse JSON
  and filter in memory, but must NOT touch a SQLAlchemy ``Session`` (sessions
  are not thread-safe). Read inputs on the caller's thread beforehand;
  persist results on the caller's thread afterwards.
* Thread-safe with respect to the LLM provider. Both the Anthropic sync
  client (httpx-based) and ``FakeLLMProvider`` (stateless) are.

Results are returned IN INPUT ORDER, so persistence loops stay deterministic
regardless of completion order. An exception in any worker propagates to the
caller — the same semantics as the sequential loop it replaces (one bad
document fails the stage, which the orchestrator already isolates).
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


def _configured_concurrency() -> int:
    from app.core.config import settings

    return max(1, int(settings.LLM_MAX_CONCURRENCY))


def run_llm_tasks(
    items: Sequence[T],
    fn: Callable[[T], R],
    *,
    max_workers: int | None = None,
) -> list[R]:
    """Run ``fn`` over ``items`` with a bounded thread pool, preserving order.

    Falls back to a plain sequential loop when there is at most one item or
    the effective concurrency is 1 — keeping stack traces simple in the
    common small-deal case and providing an escape hatch
    (``LLM_MAX_CONCURRENCY=1``) if a provider ever misbehaves under threads.
    """
    workers = max_workers if max_workers is not None else _configured_concurrency()
    if len(items) <= 1 or workers <= 1:
        return [fn(item) for item in items]

    workers = min(workers, len(items))
    logger.debug("run_llm_tasks: %d task(s) on %d worker(s)", len(items), workers)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(fn, items))
