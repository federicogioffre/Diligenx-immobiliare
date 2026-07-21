"""Tests for packages.agents.concurrency.run_llm_tasks.

The parallel LLM fan-out must preserve input order, actually run tasks
concurrently when asked to, fall back to a plain sequential loop for the
degenerate cases, and propagate worker exceptions.
"""
import threading

import pytest

from packages.agents.concurrency import run_llm_tasks


class TestOrderPreservation:
    def test_results_in_input_order(self):
        items = list(range(20))
        results = run_llm_tasks(items, lambda x: x * 2, max_workers=4)
        assert results == [x * 2 for x in items]

    def test_order_preserved_despite_variable_completion(self):
        """Workers finishing out of order must not reorder results."""
        import time

        def slow_for_early(x):
            time.sleep(0.05 if x < 2 else 0)
            return x

        items = list(range(6))
        results = run_llm_tasks(items, slow_for_early, max_workers=6)
        assert results == items


class TestParallelism:
    def test_tasks_actually_run_concurrently(self):
        """With max_workers=N and N tasks, all N must be in flight at once.

        Each worker waits on a barrier sized N — the test only passes if all
        N workers reach it simultaneously (i.e. true parallelism). A 5s
        timeout turns a sequential (deadlocked) run into a clean failure.
        """
        n = 4
        barrier = threading.Barrier(n)

        def worker(x):
            barrier.wait(timeout=5)
            return x

        results = run_llm_tasks(list(range(n)), worker, max_workers=n)
        assert results == list(range(n))

    def test_workers_bounded_by_max_workers(self):
        """Concurrent executions never exceed max_workers."""
        lock = threading.Lock()
        active = 0
        peak = 0

        def worker(x):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            import time
            time.sleep(0.02)
            with lock:
                active -= 1
            return x

        run_llm_tasks(list(range(10)), worker, max_workers=3)
        assert peak <= 3


class TestSequentialFallback:
    def test_single_item_runs_on_caller_thread(self):
        thread_ids = []

        def worker(x):
            thread_ids.append(threading.get_ident())
            return x

        run_llm_tasks([1], worker, max_workers=8)
        assert thread_ids == [threading.get_ident()]

    def test_max_workers_one_runs_on_caller_thread(self):
        thread_ids = []

        def worker(x):
            thread_ids.append(threading.get_ident())
            return x

        run_llm_tasks([1, 2, 3], worker, max_workers=1)
        assert set(thread_ids) == {threading.get_ident()}

    def test_empty_items(self):
        assert run_llm_tasks([], lambda x: x, max_workers=4) == []

    def test_uses_settings_default_when_max_workers_omitted(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "LLM_MAX_CONCURRENCY", 1)
        thread_ids = []

        def worker(x):
            thread_ids.append(threading.get_ident())
            return x

        run_llm_tasks([1, 2], worker)
        assert set(thread_ids) == {threading.get_ident()}


class TestExceptionPropagation:
    def test_worker_exception_propagates_parallel(self):
        def worker(x):
            if x == 2:
                raise ValueError("boom")
            return x

        with pytest.raises(ValueError, match="boom"):
            run_llm_tasks([1, 2, 3], worker, max_workers=3)

    def test_worker_exception_propagates_sequential(self):
        def worker(x):
            raise RuntimeError("bad")

        with pytest.raises(RuntimeError, match="bad"):
            run_llm_tasks([1, 2], worker, max_workers=1)
