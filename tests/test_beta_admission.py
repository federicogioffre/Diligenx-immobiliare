from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from app.models.deal import DealStatus
from app.models.document import Document, DocumentStatus


def test_second_analysis_is_rejected_while_first_is_queued(client, db, test_deal, auth_headers, monkeypatch):
    dispatch = AsyncMock(return_value="arq")
    monkeypatch.setattr("app.services.jobs.enqueue_or_run", dispatch)
    assert client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers).status_code == 202
    assert client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers).status_code == 409
    assert dispatch.await_count == 1


@pytest.mark.parametrize("status", [DocumentStatus.pending, DocumentStatus.processing, DocumentStatus.failed])
def test_incomplete_inventory_cannot_start_analysis(client, db, test_deal, auth_headers, monkeypatch, status):
    db.add(Document(deal_id=test_deal.id, filename="test.txt", file_path="unused", file_size=3, mime_type="text/plain", status=status))
    db.commit()
    dispatch = AsyncMock()
    monkeypatch.setattr("app.services.jobs.enqueue_or_run", dispatch)
    assert client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers).status_code == 409
    dispatch.assert_not_awaited()


def test_queue_failure_preserves_previous_deal_state(client, db, test_deal, auth_headers, monkeypatch):
    test_deal.status = DealStatus.reviewed
    db.commit()
    monkeypatch.setattr("app.services.jobs.enqueue_or_run", AsyncMock(side_effect=HTTPException(503, "Queue unavailable")))
    assert client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers).status_code == 503
    db.refresh(test_deal)
    assert test_deal.status == DealStatus.reviewed


def test_ambiguous_dispatch_keeps_inventory_locked(client, db, test_deal, auth_headers, monkeypatch):
    from app.services.jobs import JobDispatchError
    monkeypatch.setattr("app.services.jobs.enqueue_or_run", AsyncMock(side_effect=JobDispatchError("Response lost", may_have_enqueued=True)))
    assert client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers).status_code == 503
    db.refresh(test_deal)
    assert test_deal.status == DealStatus.analyzing


@pytest.mark.parametrize("job_state,expected", [("not_found", 200), ("queued", 409), ("in_progress", 409)])
def test_recovery_requires_stale_analysis_and_no_redis_job(client, db, test_deal, auth_headers, monkeypatch, job_state, expected):
    from datetime import datetime, timedelta, timezone
    from arq.jobs import Job, JobStatus
    from app.core.config import settings
    from app.main import _fastapi
    test_deal.status = DealStatus.analyzing
    # Stale means older than the whole-run job timeout plus its grace period,
    # whatever that timeout is configured to.
    test_deal.updated_at = datetime.now(timezone.utc) - timedelta(seconds=settings.WORKER_JOB_TIMEOUT_SECONDS + 120)
    db.commit()
    monkeypatch.setattr(settings, "REDIS_URL", "redis://configured")
    monkeypatch.setattr(_fastapi.state, "arq_pool", AsyncMock())
    monkeypatch.setattr(Job, "status", AsyncMock(return_value=JobStatus(job_state)))
    response = client.post(f"/deals/{test_deal.id}/recover-analysis", headers=auth_headers)
    assert response.status_code == expected, response.text
    db.refresh(test_deal)
    assert test_deal.status == (DealStatus.draft if expected == 200 else DealStatus.analyzing)


@pytest.mark.anyio
async def test_sse_releases_session_before_each_yield(db, test_deal, test_user, monkeypatch):
    from app.api.routes.deals import stream_analysis_progress
    from app.core.security import create_stream_ticket
    from app.db.session import SessionLocal
    # Use this test's engine, not the unrelated application engine.
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=db.get_bind())
    opened = []
    def session_factory():
        session = factory()
        opened.append(session)
        return session
    monkeypatch.setattr("app.db.session.SessionLocal", session_factory)
    request = AsyncMock()
    request.is_disconnected.return_value = False
    response = await stream_analysis_progress(request, test_deal.id, create_stream_ticket(test_user.email, test_deal.id), db)
    event = await anext(response.body_iterator)
    assert "deal_status" in event
    assert opened and all(not session.in_transaction() for session in opened)
    await response.body_iterator.aclose()


@pytest.fixture
def anyio_backend():
    return "asyncio"
