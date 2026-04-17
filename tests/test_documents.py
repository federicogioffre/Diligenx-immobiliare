import io


def test_upload_document(client, auth_headers, test_deal):
    file_content = b"This is a test document for upload."
    resp = client.post(
        f"/documents/upload?deal_id={test_deal.id}",
        headers=auth_headers,
        files={"file": ("test.txt", io.BytesIO(file_content), "text/plain")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"] == "test.txt"
    # Ingestion runs as a FastAPI BackgroundTask — the immediate response
    # body was serialized while the doc was still 'pending'. TestClient
    # runs background tasks inline before returning, so a subsequent GET
    # observes the final state.
    assert data["status"] in ("pending", "processed")
    assert data["file_size"] == len(file_content)

    # Verify ingestion eventually completed (background task ran).
    list_resp = client.get(
        f"/documents/deals/{test_deal.id}/documents",
        headers=auth_headers,
    )
    processed = next(
        (d for d in list_resp.json() if d["filename"] == "test.txt"), None
    )
    assert processed is not None
    assert processed["status"] == "processed"


def test_upload_unsupported_type(client, auth_headers, test_deal):
    resp = client.post(
        f"/documents/upload?deal_id={test_deal.id}",
        headers=auth_headers,
        files={"file": ("test.exe", io.BytesIO(b"binary"), "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["detail"]


def test_upload_to_nonexistent_deal(client, auth_headers):
    resp = client.post(
        "/documents/upload?deal_id=9999",
        headers=auth_headers,
        files={"file": ("test.txt", io.BytesIO(b"data"), "text/plain")},
    )
    assert resp.status_code == 404


def test_list_deal_documents(client, auth_headers, test_deal):
    # Upload a text document
    client.post(
        f"/documents/upload?deal_id={test_deal.id}",
        headers=auth_headers,
        files={"file": ("doc1.txt", io.BytesIO(b"content here"), "text/plain")},
    )

    resp = client.get(
        f"/documents/deals/{test_deal.id}/documents",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["filename"] == "doc1.txt"


def test_list_documents_nonexistent_deal(client, auth_headers):
    resp = client.get("/documents/deals/9999/documents", headers=auth_headers)
    assert resp.status_code == 404
