"""Shared per-process provider slots across all concurrently running deals.

Deploy a bounded number of worker/API processes; the fleet limit is the sum
of their slots. Provider SDK timeouts and retries apply inside each slot.
"""
from contextlib import contextmanager
from threading import BoundedSemaphore

from app.core.config import settings

_llm_slots = BoundedSemaphore(max(1, settings.LLM_MAX_IN_FLIGHT))


@contextmanager
def llm_slot():
    with _llm_slots:
        yield
