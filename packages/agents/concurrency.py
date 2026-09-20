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
regardless of completion order. By default an exception in any worker
propagates to the caller. With ``isolate_failures=True`` a failing item is
returned as a :class:`TaskFailure` in its slot instead, so one document whose
model request failed (a runaway generation truncated at the output limit, a
refusal, malformed JSON) does not discard the work done on every other
document of the stage; the stage records it and carries on. When *every* item
fails, the first error is raised, so a systemic fault (bad credentials, a
broken prompt) still fails loudly instead of degrading silently.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class TaskFailure:
    """The outcome slot of an item whose worker raised, in isolating mode."""

    error: str
    exception: BaseException


def _configured_concurrency() -> int:
    from app.core.config import settings

    return max(1, int(settings.LLM_MAX_CONCURRENCY))


def run_llm_tasks(
    items: Sequence[T],
    fn: Callable[[T], R],
    *,
    max_workers: int | None = None,
    isolate_failures: bool = False,
) -> list[R | TaskFailure]:
    """Run ``fn`` over ``items`` with a bounded thread pool, preserving order.

    Falls back to a plain sequential loop when there is at most one item or
    the effective concurrency is 1 — keeping stack traces simple in the
    common small-deal case and providing an escape hatch
    (``LLM_MAX_CONCURRENCY=1``) if a provider ever misbehaves under threads.

    With ``isolate_failures`` a raising worker yields a :class:`TaskFailure`
    in its slot; the first error is re-raised only if no item succeeded.
    """
    workers = max_workers if max_workers is not None else _configured_concurrency()
    task = _isolating(fn) if isolate_failures else fn
    if len(items) <= 1 or workers <= 1:
        results = [task(item) for item in items]
    else:
        workers = min(workers, len(items))
        logger.debug("run_llm_tasks: %d task(s) on %d worker(s)", len(items), workers)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(task, items))
    if isolate_failures and results and all(isinstance(r, TaskFailure) for r in results):
        raise results[0].exception
    return results


def _isolating(fn: Callable[[T], R]) -> Callable[[T], R | TaskFailure]:
    def task(item: T) -> R | TaskFailure:
        try:
            return fn(item)
        except Exception as exc:  # noqa: BLE001 - the failure is recorded, not hidden
            logger.warning("run_llm_tasks: task failed and was isolated: %s", exc)
            return TaskFailure(error=str(exc)[:500], exception=exc)
    return task
