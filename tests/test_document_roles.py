"""Explicit LOI uploads retain identity, tenancy and inventory locking rules."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.security import create_access_token
from app.main import _fastapi
from app.models import User
from app.models.deal import DealStatus
from app.models.document import Document, DocumentStatus


@pytest.fixture
def upload_services(monkeypatch):
    pool = SimpleNamespace(enqueue_job=AsyncMock())
    monkeypatch.setattr(_fastapi.state, "arq_pool", pool)
    storage = Mock()
    monkeypatch.setattr("app.api.routes.documents.save_file", storage)
    return pool, storage


def _upload(client, headers, deal_id, *, role=None, content=b"Agreed proposed terms"):
    params = {"deal_id": deal_id}
    if role is not None:
        params["document_role"] = role
    return client.post(
        "/documents/upload", params=params, headers=headers,
        files={"file": ("LOI.txt", content, "text/plain")},
    )


@pytest.mark.parametrize("role,expected", [(None, "data_room"), ("data_room", "data_room"), ("loi", "loi")])
def test_upload_role_is_explicit_and_visible_in_list_and_export(
    client, auth_headers, test_deal, db, upload_services, role, expected,
):
    response = _upload(client, auth_headers, test_deal.id, role=role)
    assert response.status_code == 201, response.text
    saved = db.get(Document, response.json()["id"])
    assert response.json()["document_role"] == saved.document_role == expected
    # The LOI filename must not turn a normal data-room upload into a LOI.
    listed = client.get(f"/documents/deals/{test_deal.id}/documents", headers=auth_headers)
    assert listed.json()[0]["document_role"] == expected
    exported = client.get("/users/me/export", headers=auth_headers)
    assert exported.json()["workspaces"][0]["deals"][0]["documents"][0]["document_role"] == expected


@pytest.mark.parametrize("role", ["", "LOI", "contract", "loi,data_room"])
def test_invalid_upload_role_rejected_before_storage(
    client, auth_headers, test_deal, db, upload_services, role,
):
    response = _upload(client, auth_headers, test_deal.id, role=role)
    assert response.status_code == 422
    assert db.query(Document).count() == 0
    pool, storage = upload_services
    storage.assert_not_called()
    pool.enqueue_job.assert_not_awaited()


def test_loi_enqueue_failure_can_be_retried_without_duplicate_or_demotion(
    client, auth_headers, test_deal, db, upload_services,
):
    pool, storage = upload_services
    pool.enqueue_job.side_effect = ConnectionError("queue unavailable")
    response = _upload(client, auth_headers, test_deal.id, role="loi")
    assert response.status_code == 503
    original_id = db.query(Document).one().id
    pool.enqueue_job.side_effect = None

    for role in ("loi", None, "data_room"):
        retried = _upload(client, auth_headers, test_deal.id, role=role)
        assert retried.status_code == 201, retried.text
        assert retried.json()["id"] == original_id
        assert retried.json()["document_role"] == "loi"
    assert db.query(Document).count() == 1
    storage.assert_called_once()


def test_explicit_loi_promotes_same_document_without_reingestion(
    client, auth_headers, test_deal, db, upload_services,
):
    pool, storage = upload_services
    first = _upload(client, auth_headers, test_deal.id)
    saved = db.get(Document, first.json()["id"])
    saved.status = DocumentStatus.processed
    saved.raw_text = "Preserved extracted terms"
    db.commit()
    pool.enqueue_job.reset_mock()
    storage.reset_mock()

    response = _upload(client, auth_headers, test_deal.id, role="loi")

    assert response.status_code == 201, response.text
    assert response.json()["id"] == saved.id
    assert response.json()["document_role"] == "loi"
    db.refresh(saved)
    assert saved.document_role == "loi"
    assert saved.raw_text == "Preserved extracted terms"
    assert db.query(Document).count() == 1
    pool.enqueue_job.assert_not_awaited()
    storage.assert_not_called()


@pytest.mark.parametrize("status", list(DocumentStatus))
def test_analysis_rejects_role_promotion_without_document_changes(
    client, auth_headers, test_deal, db, upload_services, status,
):
    pool, storage = upload_services
    first = _upload(client, auth_headers, test_deal.id)
    saved = db.get(Document, first.json()["id"])
    saved.status = status
    saved.raw_text = "Retained extraction"
    test_deal.status = DealStatus.analyzing
    db.commit()
    pool.enqueue_job.reset_mock()
    storage.reset_mock()

    response = _upload(client, auth_headers, test_deal.id, role="loi")

    assert response.status_code == 409
    db.refresh(saved)
    assert saved.document_role == "data_room"
    assert saved.status == status
    assert saved.raw_text == "Retained extraction"
    storage.assert_not_called()
    pool.enqueue_job.assert_not_awaited()


def test_processed_loi_retry_during_analysis_is_an_idempotent_noop(
    client, auth_headers, test_deal, db, upload_services,
):
    pool, storage = upload_services
    first = _upload(client, auth_headers, test_deal.id, role="loi")
    saved = db.get(Document, first.json()["id"])
    saved.status = DocumentStatus.processed
    test_deal.status = DealStatus.analyzing
    db.commit()
    pool.enqueue_job.reset_mock()
    storage.reset_mock()
    for role in ("loi", None):
        response = _upload(client, auth_headers, test_deal.id, role=role)
        assert response.status_code == 201, response.text
        assert response.json()["id"] == saved.id
        assert response.json()["document_role"] == "loi"
    pool.enqueue_job.assert_not_awaited()
    storage.assert_not_called()


def test_loi_uploads_and_promotions_cannot_access_another_owner(
    client, auth_headers, test_deal, test_user, db, upload_services,
):
    pool, storage = upload_services
    first = _upload(client, auth_headers, test_deal.id)
    saved = db.get(Document, first.json()["id"])
    other = User(email="other-loi@example.com", hashed_password=test_user.hashed_password)
    db.add(other)
    db.commit()
    other_headers = {"Authorization": f"Bearer {create_access_token(other.email)}"}
    pool.enqueue_job.reset_mock()
    storage.reset_mock()

    for content in (b"Agreed proposed terms", b"Another proposed transaction"):
        response = _upload(client, other_headers, test_deal.id, role="loi", content=content)
        assert response.status_code == 404
    db.refresh(saved)
    assert saved.document_role == "data_room"
    assert db.query(Document).count() == 1
    storage.assert_not_called()
    pool.enqueue_job.assert_not_awaited()


def test_batch_defaults_to_data_room_and_preserves_existing_loi(
    client, auth_headers, test_deal, db, upload_services,
):
    first = _upload(client, auth_headers, test_deal.id, role="loi")
    response = client.post(
        f"/documents/upload-batch?deal_id={test_deal.id}", headers=auth_headers,
        files=[
            ("files", ("LOI.txt", b"Agreed proposed terms", "text/plain")),
            ("files", ("Another LOI.txt", b"Normal data-room file", "text/plain")),
        ],
    )
    assert response.status_code == 201, response.text
    assert response.json()[0]["id"] == first.json()["id"]
    assert [item["document_role"] for item in response.json()] == ["loi", "data_room"]
    assert db.query(Document).count() == 2


def test_failed_loi_upload_retry_retains_role(
    client, auth_headers, test_deal, db, upload_services,
):
    response = _upload(client, auth_headers, test_deal.id, role="loi")
    saved = db.get(Document, response.json()["id"])
    saved.status = DocumentStatus.failed
    db.commit()
    retried = _upload(client, auth_headers, test_deal.id)
    assert retried.status_code == 201
    assert retried.json()["id"] == saved.id
    assert retried.json()["document_role"] == "loi"
    assert retried.json()["status"] == "pending"
