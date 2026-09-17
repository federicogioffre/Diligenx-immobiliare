from unittest.mock import AsyncMock
import pytest
from app.core.config import settings
from app.main import _fastapi


@pytest.mark.parametrize("alive,code", [(True, 200), (False, 503)])
def test_readiness_requires_worker_heartbeat(client, monkeypatch, alive, code):
    pool = AsyncMock()
    pool.exists.return_value = alive
    monkeypatch.setattr(settings, "REDIS_URL", "redis://configured")
    monkeypatch.setattr(_fastapi.state, "arq_pool", pool)
    response = client.get("/health")
    assert response.status_code == code
    assert response.json()["worker"] == ("ok" if alive else "unavailable")


def test_readiness_fails_when_queue_disappears(client, monkeypatch):
    pool = AsyncMock()
    pool.ping.side_effect = ConnectionError("offline")
    monkeypatch.setattr(settings, "REDIS_URL", "redis://configured")
    monkeypatch.setattr(_fastapi.state, "arq_pool", pool)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["queue"] == "unreachable"
