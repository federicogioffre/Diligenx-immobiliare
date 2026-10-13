import pytest

from app import worker
from app.core.runtime_validation import PendingMigrationsError


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    monkeypatch.setattr(worker, "MIGRATION_POLL_SECONDS", 0)
    monkeypatch.setattr("app.core.runtime_validation.validate_beta_configuration", lambda: None)


@pytest.mark.anyio
async def test_worker_waits_for_the_api_to_migrate(monkeypatch):
    checks = []

    def validate():
        checks.append(1)
        if len(checks) < 3:
            raise PendingMigrationsError("BETA_MODE requires all current database migrations")

    monkeypatch.setattr("app.core.runtime_validation.validate_beta_database", validate)
    await worker._startup({})
    assert len(checks) == 3


@pytest.mark.anyio
async def test_worker_gives_up_when_migrations_never_arrive(monkeypatch):
    def validate():
        raise PendingMigrationsError("BETA_MODE requires all current database migrations")

    monkeypatch.setattr("app.core.runtime_validation.validate_beta_database", validate)
    monkeypatch.setattr(worker, "MIGRATION_WAIT_SECONDS", 0)
    with pytest.raises(PendingMigrationsError):
        await worker._startup({})


@pytest.mark.anyio
async def test_other_beta_failures_stop_the_worker_at_once(monkeypatch):
    checks = []

    def validate():
        checks.append(1)
        raise RuntimeError("BETA_MODE requires an application role without SUPERUSER or BYPASSRLS")

    monkeypatch.setattr("app.core.runtime_validation.validate_beta_database", validate)
    with pytest.raises(RuntimeError, match="SUPERUSER"):
        await worker._startup({})
    assert len(checks) == 1
