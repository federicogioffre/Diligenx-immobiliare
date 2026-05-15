"""Tests for the durable-job dispatch abstraction (app.services.jobs).

The default path (no Arq pool) must keep behaving exactly like before —
FastAPI BackgroundTasks runs the job in-process — so every other test in
the suite continues to pass without changes. When an Arq pool IS attached
to ``app.state``, ``enqueue_or_run`` must route to ``pool.enqueue_job``
instead of falling back.
"""

from unittest.mock import AsyncMock

import pytest

from app.services.jobs import enqueue_or_run


class _FakeAppState:
    def __init__(self, pool):
        self.arq_pool = pool


class _FakeApp:
    def __init__(self, pool):
        self.state = _FakeAppState(pool)


class _FakeRequest:
    def __init__(self, pool):
        self.app = _FakeApp(pool)


class _FakeBackgroundTasks:
    def __init__(self):
        self.added: list = []

    def add_task(self, func, *args, **kwargs):
        self.added.append((func, args, kwargs))


def _sentinel():  # placeholder; never called when Arq is configured
    raise AssertionError("sync fallback should not run when Arq is configured")


# ── fallback path ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_falls_back_to_background_tasks_when_no_pool():
    request = _FakeRequest(pool=None)
    bg = _FakeBackgroundTasks()

    def sync_fn(deal_id: int):
        pass

    where = await enqueue_or_run(
        request, bg, "run_pipeline_for_deal", sync_fn, 42,
    )

    assert where == "background_tasks"
    assert len(bg.added) == 1
    assert bg.added[0] == (sync_fn, (42,), {})


# ── arq path ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_uses_arq_pool_when_configured():
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    request = _FakeRequest(pool=pool)
    bg = _FakeBackgroundTasks()

    where = await enqueue_or_run(
        request, bg, "run_pipeline_for_deal", _sentinel, 123,
    )

    assert where == "arq"
    pool.enqueue_job.assert_awaited_once_with("run_pipeline_for_deal", 123)
    assert bg.added == []


@pytest.mark.anyio
async def test_arq_enqueue_failure_falls_back_to_background_tasks():
    """If Redis is down at enqueue time, we should still run the job."""
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(side_effect=ConnectionError("redis down"))
    request = _FakeRequest(pool=pool)
    bg = _FakeBackgroundTasks()

    def sync_fn(doc_id: int):
        pass

    where = await enqueue_or_run(
        request, bg, "run_ingestion_for_document", sync_fn, 7,
    )

    assert where == "background_tasks"
    pool.enqueue_job.assert_awaited_once()
    assert bg.added == [(sync_fn, (7,), {})]


# ── pytest-anyio config: required for the async test functions above ─────


@pytest.fixture
def anyio_backend():
    return "asyncio"
