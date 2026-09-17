"""Upload retry and queue dispatch regressions, without calling real providers."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.main import _fastapi
from app.models.document import Document, DocumentStatus
from app.models.deal import DealStatus


def _file(content=b"contract content", name="contract.txt"):
    return {"file": (name, content, "text/plain")}


def _pool(monkeypatch, *, fail=False):
    pool = SimpleNamespace(enqueue_job=AsyncMock(side_effect=ConnectionError("queue unavailable") if fail else None))
    monkeypatch.setattr(_fastapi.state, "arq_pool", pool)
    return pool


def test_retry_after_enqueue_failure_reuses_saved_document(client, auth_headers, test_deal, db, monkeypatch):
    _pool(monkeypatch, fail=True)
    url = f"/documents/upload?deal_id={test_deal.id}"
    failed = client.post(url, headers=auth_headers, files=_file())
    assert failed.status_code == 503
    assert failed.headers["retry-after"] == "10"
    saved = db.query(Document).one()
    original_id = saved.id
    assert saved.status == DocumentStatus.pending

    pool = _pool(monkeypatch)
    retried = client.post(url, headers=auth_headers, files=_file())
    assert retried.status_code == 201
    assert retried.json()["id"] == original_id
    assert db.query(Document).count() == 1
    pool.enqueue_job.assert_awaited_once_with(
        "run_ingestion_for_document", original_id, test_deal.workspace.owner_id,
        _job_id=f"ingestion:{original_id}",
    )


def test_batch_uses_durable_queue_and_is_idempotent(client, auth_headers, test_deal, db, monkeypatch):
    pool = _pool(monkeypatch)
    files = [("files", ("one.txt", b"one", "text/plain")), ("files", ("two.txt", b"two", "text/plain"))]
    url = f"/documents/upload-batch?deal_id={test_deal.id}"
    first = client.post(url, headers=auth_headers, files=files)
    assert first.status_code == 201
    assert pool.enqueue_job.await_count == 2
    again = client.post(url, headers=auth_headers, files=files)
    assert again.status_code == 201
    assert [item["id"] for item in first.json()] == [item["id"] for item in again.json()]
    assert db.query(Document).count() == 2


def test_processed_retry_does_not_restart_ingestion(client, auth_headers, test_deal, db, monkeypatch):
    pool = _pool(monkeypatch)
    url = f"/documents/upload?deal_id={test_deal.id}"
    first = client.post(url, headers=auth_headers, files=_file())
    saved = db.get(Document, first.json()["id"])
    saved.status = DocumentStatus.processed
    db.commit()
    pool.enqueue_job.reset_mock()
    again = client.post(url, headers=auth_headers, files=_file())
    assert again.json()["id"] == saved.id
    pool.enqueue_job.assert_not_awaited()


def test_same_name_different_content_is_a_distinct_document(client, auth_headers, test_deal, db, monkeypatch):
    _pool(monkeypatch)
    url = f"/documents/upload?deal_id={test_deal.id}"
    first = client.post(url, headers=auth_headers, files=_file(b"first revision"))
    second = client.post(url, headers=auth_headers, files=_file(b"second revision"))
    assert first.json()["id"] != second.json()["id"]
    assert db.query(Document).count() == 2


def test_analysis_inventory_cannot_be_changed(client, auth_headers, test_deal, db, monkeypatch):
    _pool(monkeypatch)
    first = client.post(f"/documents/upload?deal_id={test_deal.id}", headers=auth_headers, files=_file())
    test_deal.status = DealStatus.analyzing
    db.commit()
    response = client.post(f"/documents/upload?deal_id={test_deal.id}", headers=auth_headers, files=_file(b"another"))
    assert response.status_code == 409
    response = client.delete(f"/documents/{first.json()['id']}", headers=auth_headers)
    assert response.status_code == 409
    assert db.query(Document).count() == 1


def test_upload_limit_is_shared_per_user_but_not_per_office_ip(client, auth_headers, test_deal, test_user, db, monkeypatch):
    from app.core.config import settings
    from app.core.limiter import limiter
    from app.core.security import create_access_token
    from app.models import User, Workspace, Deal

    _pool(monkeypatch)
    monkeypatch.setattr(settings, "UPLOAD_RATE_LIMIT", "1/minute")
    second = User(email="other-uploader@example.com", hashed_password=test_user.hashed_password, full_name="Other")
    db.add(second)
    db.flush()
    workspace = Workspace(name="Second workspace", owner_id=second.id)
    db.add(workspace)
    db.flush()
    deal = Deal(title="Second deal", workspace_id=workspace.id)
    db.add(deal)
    db.commit()
    second_headers = {"Authorization": f"Bearer {create_access_token(second.email)}"}
    limiter.enabled = True
    limiter.reset()

    first = client.post(f"/documents/upload?deal_id={test_deal.id}", headers=auth_headers, files=_file())
    limited = client.post(f"/documents/upload?deal_id={test_deal.id}", headers=auth_headers, files=_file())
    other = client.post(f"/documents/upload?deal_id={deal.id}", headers=second_headers, files=_file())
    assert first.status_code == 201
    assert limited.status_code == 429
    assert other.status_code == 201

