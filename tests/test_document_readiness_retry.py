"""Recover saved documents without uploading them again or losing prior content."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from arq.jobs import Job, JobStatus
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import create_access_token
from app.main import _fastapi
from app.models import User
from app.models.deal import DealStatus
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk


def _document(db, deal, *, status=DocumentStatus.failed, raw_text=None, name="contract.txt"):
    document = Document(
        deal_id=deal.id,
        filename=name,
        file_path=f"deals/{deal.id}/retained-{name}",
        mime_type="text/plain",
        file_size=123,
        status=status,
        raw_text=raw_text,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _redis(monkeypatch, *, status=JobStatus.not_found, status_error=None, enqueue_error=None):
    monkeypatch.setattr(settings, "REDIS_URL", "redis://configured")
    pool = SimpleNamespace(enqueue_job=AsyncMock(side_effect=enqueue_error))
    monkeypatch.setattr(_fastapi.state, "arq_pool", pool)
    lookup = AsyncMock(return_value=status, side_effect=status_error)
    monkeypatch.setattr(Job, "status", lookup)
    return pool, lookup


@pytest.mark.parametrize(
    "status,text,ready,issue",
    [
        (DocumentStatus.pending, "Earlier content", False, "pending"),
        (DocumentStatus.processing, "Earlier content", False, "processing"),
        (DocumentStatus.failed, "Earlier content", False, "failed"),
        (DocumentStatus.processed, None, False, "missing_text"),
        (DocumentStatus.processed, "", False, "missing_text"),
        (DocumentStatus.processed, " \n\t ", False, "missing_text"),
        (DocumentStatus.processed, " \nReadable contract\t ", True, None),
    ],
)
def test_document_list_explains_readiness_without_exposing_text(
    client, auth_headers, test_deal, db, status, text, ready, issue,
):
    document = _document(db, test_deal, status=status, raw_text=text)
    response = client.get(f"/documents/deals/{test_deal.id}/documents", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    item = response.json()[0]
    assert item["id"] == document.id
    assert item["status"] == status.value
    assert item["analysis_ready"] is ready
    assert item["processing_issue"] == issue
    assert "raw_text" not in item
    assert "file_path" not in item


def test_analysis_reports_every_blocking_document_and_preserves_deal_state(
    client, auth_headers, test_deal, db, monkeypatch,
):
    test_deal.status = DealStatus.reviewed
    expected = []
    for index, (status, text, reason) in enumerate([
        (DocumentStatus.pending, None, "pending"),
        (DocumentStatus.processing, None, "processing"),
        (DocumentStatus.failed, "PRIVATE PRIOR EXTRACTION", "failed"),
        (DocumentStatus.processed, " \n\t ", "missing_text"),
    ]):
        doc = _document(db, test_deal, status=status, raw_text=text, name=f"blocked-{index}.txt")
        expected.append({"id": doc.id, "filename": doc.filename, "status": status.value, "reason": reason})
    _document(db, test_deal, status=DocumentStatus.processed, raw_text="PRIVATE READY EXTRACTION", name="ready.txt")
    dispatch = AsyncMock()
    monkeypatch.setattr("app.services.jobs.enqueue_or_run", dispatch)

    response = client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "documents_not_ready"
    assert isinstance(detail["message"], str) and detail["message"].strip()
    assert sorted(detail["documents"], key=lambda item: item["id"]) == expected
    assert "PRIVATE" not in response.text
    assert "raw_text" not in response.text
    dispatch.assert_not_awaited()
    db.refresh(test_deal)
    assert test_deal.status == DealStatus.reviewed


def test_processed_readable_document_can_start_analysis(client, auth_headers, test_deal, db, monkeypatch):
    _document(db, test_deal, status=DocumentStatus.processed, raw_text=" \nContract body\t ")
    dispatch = AsyncMock(return_value="arq")
    monkeypatch.setattr("app.services.jobs.enqueue_or_run", dispatch)
    response = client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
    assert response.status_code == 202, response.text
    dispatch.assert_awaited_once()


@pytest.mark.parametrize(
    "status,text",
    [(DocumentStatus.failed, "Preserve earlier extracted content"), (DocumentStatus.processed, " \n\t ")],
)
def test_retry_reuses_saved_object_and_preserves_text_and_chunks(
    client, auth_headers, test_deal, db, monkeypatch, status, text,
):
    document = _document(db, test_deal, status=status, raw_text=text)
    chunk = DocumentChunk(document_id=document.id, chunk_index=0, content="Retain previous chunk")
    db.add(chunk)
    db.commit()
    document_id, object_key, chunk_id = document.id, document.file_path, chunk.id
    pool, _ = _redis(monkeypatch)
    save = Mock(side_effect=AssertionError("Retry must reuse the stored object"))
    delete = Mock(side_effect=AssertionError("Retry must not delete the stored object"))
    monkeypatch.setattr("app.api.routes.documents.save_file", save)
    monkeypatch.setattr("app.api.routes.documents.delete_file", delete)

    response = client.post(f"/documents/{document_id}/retry", headers=auth_headers)

    assert response.status_code == 202, response.text
    assert response.json()["id"] == document_id
    assert response.json()["status"] == "pending"
    assert response.json()["analysis_ready"] is False
    assert response.json()["processing_issue"] == "pending"
    pool.enqueue_job.assert_awaited_once_with(
        "run_ingestion_for_document", document_id, test_deal.workspace.owner_id,
        _job_id=f"ingestion:{document_id}",
    )
    db.refresh(document)
    assert document.status == DocumentStatus.pending
    assert document.raw_text == text
    assert document.file_path == object_key
    assert db.query(Document).count() == 1
    assert db.get(DocumentChunk, chunk_id).content == "Retain previous chunk"
    save.assert_not_called()
    delete.assert_not_called()


def test_retry_is_scoped_to_document_owner(client, auth_headers, test_deal, test_user, db, monkeypatch):
    document = _document(db, test_deal)
    other = User(email="other-retry@example.com", hashed_password=test_user.hashed_password, full_name="Other")
    db.add(other)
    db.commit()
    other_headers = {"Authorization": f"Bearer {create_access_token(other.email)}"}
    pool, lookup = _redis(monkeypatch)

    response = client.post(f"/documents/{document.id}/retry", headers=other_headers)
    missing = client.post("/documents/999999/retry", headers=auth_headers)

    assert response.status_code == missing.status_code == 404
    pool.enqueue_job.assert_not_awaited()
    lookup.assert_not_awaited()
    db.refresh(document)
    assert document.status == DocumentStatus.failed


def test_readiness_and_analysis_details_are_invisible_to_other_owners(
    client, test_deal, test_user, db, monkeypatch,
):
    document = _document(
        db, test_deal, status=DocumentStatus.failed,
        raw_text="PRIVATE OWNER DOCUMENT CONTENT", name="private-owner-contract.txt",
    )
    other = User(email="other-readiness@example.com", hashed_password=test_user.hashed_password, full_name="Other")
    db.add(other)
    db.commit()
    other_headers = {"Authorization": f"Bearer {create_access_token(other.email)}"}
    dispatch = AsyncMock()
    monkeypatch.setattr("app.services.jobs.enqueue_or_run", dispatch)

    responses = [
        client.get(f"/documents/deals/{test_deal.id}/documents", headers=other_headers),
        client.post(f"/deals/{test_deal.id}/analyze", headers=other_headers),
    ]

    for response in responses:
        assert response.status_code == 404, response.text
        assert document.filename not in response.text
        assert document.raw_text not in response.text
        assert str(document.id) not in response.text
        assert "documents_not_ready" not in response.text
        assert "documents" not in response.json()
    dispatch.assert_not_awaited()


def test_retry_cannot_change_inventory_while_analysis_runs(client, auth_headers, test_deal, db, monkeypatch):
    document = _document(db, test_deal)
    test_deal.status = DealStatus.analyzing
    db.commit()
    pool, lookup = _redis(monkeypatch)
    response = client.post(f"/documents/{document.id}/retry", headers=auth_headers)
    assert response.status_code == 409, response.text
    pool.enqueue_job.assert_not_awaited()
    lookup.assert_not_awaited()
    db.refresh(document)
    assert document.status == DocumentStatus.failed


@pytest.mark.parametrize("status", [DocumentStatus.pending, DocumentStatus.processing, DocumentStatus.failed, DocumentStatus.processed])
@pytest.mark.parametrize("job_status", [JobStatus.queued, JobStatus.in_progress, JobStatus.deferred, JobStatus.complete])
def test_retry_does_not_restart_active_ingestion(
    client, auth_headers, test_deal, db, monkeypatch, status, job_status,
):
    old_text = " \n " if status == DocumentStatus.processed else "Retained text"
    document = _document(db, test_deal, status=status, raw_text=old_text)
    pool, lookup = _redis(monkeypatch, status=job_status)
    response = client.post(f"/documents/{document.id}/retry", headers=auth_headers)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "ingestion_already_active"
    lookup.assert_awaited_once()
    pool.enqueue_job.assert_not_awaited()
    db.refresh(document)
    assert document.status == status
    assert document.raw_text == old_text


@pytest.mark.parametrize("status", [DocumentStatus.pending, DocumentStatus.processing])
def test_retry_recovers_orphaned_ingestion_after_confirming_missing_job(
    client, auth_headers, test_deal, db, monkeypatch, status,
):
    document = _document(db, test_deal, status=status)
    pool, lookup = _redis(monkeypatch, status=JobStatus.not_found)
    response = client.post(f"/documents/{document.id}/retry", headers=auth_headers)
    assert response.status_code == 202, response.text
    lookup.assert_awaited_once()
    pool.enqueue_job.assert_awaited_once_with(
        "run_ingestion_for_document", document.id, test_deal.workspace.owner_id,
        _job_id=f"ingestion:{document.id}",
    )
    db.refresh(document)
    assert document.status == DocumentStatus.pending


@pytest.mark.parametrize("status", [DocumentStatus.pending, DocumentStatus.processing, DocumentStatus.failed, DocumentStatus.processed])
def test_retry_configured_queue_missing_never_uses_background_tasks(
    client, auth_headers, test_deal, db, monkeypatch, status,
):
    old_text = " \n " if status == DocumentStatus.processed else "Preserved text"
    document = _document(db, test_deal, status=status, raw_text=old_text)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://configured")
    monkeypatch.setattr(_fastapi.state, "arq_pool", None)
    background = Mock()
    monkeypatch.setattr("app.api.routes.documents._run_ingestion", background)
    response = client.post(f"/documents/{document.id}/retry", headers=auth_headers)
    assert response.status_code == 503, response.text
    background.assert_not_called()
    db.refresh(document)
    assert document.status == status
    assert document.raw_text == old_text


@pytest.mark.parametrize("status", [DocumentStatus.pending, DocumentStatus.processing, DocumentStatus.failed, DocumentStatus.processed])
def test_retry_queue_status_error_fails_closed(client, auth_headers, test_deal, db, monkeypatch, status):
    document = _document(db, test_deal, status=status)
    pool, lookup = _redis(monkeypatch, status_error=ConnectionError("status unavailable"))
    background = Mock()
    monkeypatch.setattr("app.api.routes.documents._run_ingestion", background)
    response = client.post(f"/documents/{document.id}/retry", headers=auth_headers)
    assert response.status_code == 503, response.text
    lookup.assert_awaited_once()
    pool.enqueue_job.assert_not_awaited()
    background.assert_not_called()
    db.refresh(document)
    assert document.status == status


def test_retry_already_ready_document_is_an_idempotent_noop(client, auth_headers, test_deal, db, monkeypatch):
    document = _document(db, test_deal, status=DocumentStatus.processed, raw_text=" Complete document ")
    pool, lookup = _redis(monkeypatch)
    response = client.post(f"/documents/{document.id}/retry", headers=auth_headers)
    assert response.status_code == 202, response.text
    assert response.json()["id"] == document.id
    assert response.json()["analysis_ready"] is True
    assert response.json()["processing_issue"] is None
    assert response.json()["status"] == "processed"
    pool.enqueue_job.assert_not_awaited()
    lookup.assert_not_awaited()
    db.refresh(document)
    assert document.raw_text == " Complete document "


def test_retry_enqueue_error_never_falls_back_to_background(client, auth_headers, test_deal, db, monkeypatch):
    document = _document(db, test_deal)
    pool, _ = _redis(monkeypatch, enqueue_error=TimeoutError("queue reply lost"))
    background = Mock()
    monkeypatch.setattr("app.api.routes.documents._run_ingestion", background)
    response = client.post(f"/documents/{document.id}/retry", headers=auth_headers)
    assert response.status_code == 503, response.text
    pool.enqueue_job.assert_awaited_once()
    background.assert_not_called()


@pytest.mark.parametrize("status", [DocumentStatus.pending, DocumentStatus.processing])
def test_retry_without_redis_cannot_prove_pending_job_is_orphaned(
    client, auth_headers, test_deal, db, monkeypatch, status,
):
    document = _document(db, test_deal, status=status)
    monkeypatch.setattr(settings, "REDIS_URL", "")
    monkeypatch.setattr(_fastapi.state, "arq_pool", None)
    background = Mock()
    monkeypatch.setattr("app.api.routes.documents._run_ingestion", background)
    response = client.post(f"/documents/{document.id}/retry", headers=auth_headers)
    assert response.status_code == 409, response.text
    background.assert_not_called()
    db.refresh(document)
    assert document.status == status


@pytest.mark.parametrize("status", [DocumentStatus.failed, DocumentStatus.processed])
def test_retry_failed_or_empty_document_supports_explicit_local_mode(
    client, auth_headers, test_deal, db, monkeypatch, status,
):
    document = _document(db, test_deal, status=status, raw_text=" \n ")
    monkeypatch.setattr(settings, "REDIS_URL", "")
    monkeypatch.setattr(_fastapi.state, "arq_pool", None)
    background = Mock()
    monkeypatch.setattr("app.api.routes.documents._run_ingestion", background)
    response = client.post(f"/documents/{document.id}/retry", headers=auth_headers)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "pending"
    background.assert_called_once_with(document.id, test_deal.workspace.owner_id)


@pytest.mark.parametrize("text,should_process", [(None, True), ("", True), (" \n\t ", True), (" Contract body ", False)])
def test_worker_only_skips_processed_documents_with_readable_text(db, test_deal, monkeypatch, text, should_process):
    from app import worker

    document = _document(db, test_deal, status=DocumentStatus.processed, raw_text=text)
    factory = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    process = Mock()
    monkeypatch.setattr("packages.parsing.ingestion_pipeline.process_document", process)

    worker._run_ingestion(document.id, test_deal.workspace.owner_id)

    if should_process:
        process.assert_called_once()
        assert process.call_args.args[0] == document.id
    else:
        process.assert_not_called()
