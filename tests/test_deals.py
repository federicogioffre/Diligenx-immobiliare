def test_create_deal(client, auth_headers, test_workspace):
    resp = client.post(
        f"/deals/?workspace_id={test_workspace.id}",
        json={"title": "New Deal", "description": "A new deal", "value": 500_000},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "New Deal"
    assert data["workspace_id"] == test_workspace.id
    assert data["status"] == "draft"


def test_create_deal_unauthorized(client, test_workspace):
    resp = client.post(
        f"/deals/?workspace_id={test_workspace.id}",
        json={"title": "Unauthorized"},
    )
    assert resp.status_code in (401, 403)


def test_list_deals(client, auth_headers, test_workspace, test_deal):
    resp = client.get(
        f"/deals/?workspace_id={test_workspace.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["title"] == "Test Deal"


def test_list_deals_wrong_workspace(client, auth_headers):
    resp = client.get("/deals/?workspace_id=9999", headers=auth_headers)
    assert resp.status_code == 404


def test_get_deal(client, auth_headers, test_deal):
    resp = client.get(f"/deals/{test_deal.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == test_deal.id


def test_get_deal_not_found(client, auth_headers):
    resp = client.get("/deals/9999", headers=auth_headers)
    assert resp.status_code == 404
