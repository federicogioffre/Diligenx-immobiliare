"""Tests for /workspaces endpoints — CRUD + ownership + delete guards."""

from app.core.security import create_access_token, hash_password
from app.models.deal import Deal
from app.models.user import User
from app.models.workspace import Workspace


# ── helpers ────────────────────────────────────────────────────────────────


def _make_other_user(db):
    """Create a second user with their own workspace and return (user, ws, headers)."""
    other = User(
        email="other@example.com",
        hashed_password=hash_password("otherpass"),
        full_name="Other User",
    )
    db.add(other)
    db.commit()
    db.refresh(other)

    other_ws = Workspace(name="Other Workspace", owner_id=other.id)
    db.add(other_ws)
    db.commit()
    db.refresh(other_ws)

    headers = {"Authorization": f"Bearer {create_access_token(other.email, user_id=other.id, hashed_password=other.hashed_password)}"}
    return other, other_ws, headers


# ── list / create (smoke tests for existing endpoints) ─────────────────────


def test_list_workspaces_scoped_to_owner(client, auth_headers, test_workspace, db):
    # Another user's workspace must NOT leak into the list
    _make_other_user(db)

    resp = client.get("/workspaces/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == test_workspace.id


def test_create_workspace(client, auth_headers):
    resp = client.post(
        "/workspaces/",
        json={"name": "Alpha", "description": "Client A deal-room"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Alpha"
    assert data["description"] == "Client A deal-room"
    assert "id" in data


# ── GET /{id} ──────────────────────────────────────────────────────────────


def test_get_workspace_by_owner(client, auth_headers, test_workspace):
    resp = client.get(f"/workspaces/{test_workspace.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == test_workspace.id


def test_get_workspace_of_other_user_returns_404(client, auth_headers, db):
    _, other_ws, _ = _make_other_user(db)
    resp = client.get(f"/workspaces/{other_ws.id}", headers=auth_headers)
    # 404 (not 403) — we don't leak existence
    assert resp.status_code == 404


# ── PATCH /{id} ────────────────────────────────────────────────────────────


def test_patch_workspace_name_and_description(client, auth_headers, test_workspace):
    resp = client.patch(
        f"/workspaces/{test_workspace.id}",
        json={"name": "Renamed", "description": "Updated desc"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Renamed"
    assert data["description"] == "Updated desc"


def test_patch_workspace_partial_update(client, auth_headers, test_workspace):
    # Only change name; description should remain whatever it was
    resp = client.patch(
        f"/workspaces/{test_workspace.id}",
        json={"name": "Only name changed"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Only name changed"


def test_patch_workspace_of_other_user_returns_404(client, auth_headers, db):
    _, other_ws, _ = _make_other_user(db)
    resp = client.patch(
        f"/workspaces/{other_ws.id}",
        json={"name": "Hijack"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── DELETE /{id} ───────────────────────────────────────────────────────────


def test_delete_last_workspace_blocked(client, auth_headers, test_workspace):
    # test_workspace is the user's only workspace → cannot delete
    resp = client.delete(f"/workspaces/{test_workspace.id}", headers=auth_headers)
    assert resp.status_code == 409
    assert "last workspace" in resp.json()["detail"].lower()


def test_delete_workspace_with_deals_blocked(client, auth_headers, test_workspace, test_deal, db, test_user):
    # Create a second workspace so the target isn't "last", but target still
    # contains test_deal → must still be refused with 409
    second = Workspace(name="Second", owner_id=test_user.id)
    db.add(second)
    db.commit()

    resp = client.delete(f"/workspaces/{test_workspace.id}", headers=auth_headers)
    assert resp.status_code == 409
    assert "deal" in resp.json()["detail"].lower()


def test_delete_empty_workspace_succeeds(client, auth_headers, test_workspace, db, test_user):
    # Create a second workspace (empty) — deleting it should succeed
    second = Workspace(name="Disposable", owner_id=test_user.id)
    db.add(second)
    db.commit()
    db.refresh(second)

    resp = client.delete(f"/workspaces/{second.id}", headers=auth_headers)
    assert resp.status_code == 204

    # Confirm gone
    check = client.get(f"/workspaces/{second.id}", headers=auth_headers)
    assert check.status_code == 404


def test_delete_workspace_of_other_user_returns_404(client, auth_headers, db):
    _, other_ws, _ = _make_other_user(db)
    resp = client.delete(f"/workspaces/{other_ws.id}", headers=auth_headers)
    assert resp.status_code == 404
