def test_register(client):
    resp = client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "secret123", "full_name": "New User"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "new@example.com"
    assert data["full_name"] == "New User"
    assert "id" in data


def test_register_duplicate(client, test_user):
    resp = client.post(
        "/auth/register",
        json={"email": test_user.email, "password": "secret123"},
    )
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"]


def test_login(client, test_user):
    resp = client.post(
        "/auth/login",
        data={"username": test_user.email, "password": "testpass123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_bad_password(client, test_user):
    resp = client.post(
        "/auth/login",
        data={"username": test_user.email, "password": "wrong"},
    )
    assert resp.status_code == 401
