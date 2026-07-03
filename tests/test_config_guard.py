"""Tests for the production startup guard on the JWT signing key.

``_validate_runtime_secrets`` runs at app startup (in the lifespan) and must
refuse to boot a production-like deployment that still uses the committed
default ``SECRET_KEY`` — which would let anyone forge auth tokens.
"""
import pytest

from app.core.config import settings
from app.main import _validate_runtime_secrets, _DEFAULT_SECRET_KEY


def test_allows_default_secret_on_sqlite(monkeypatch):
    """The SQLite test/dev context is exempt so the suite keeps running."""
    monkeypatch.setattr(settings, "SECRET_KEY", _DEFAULT_SECRET_KEY)
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///./test.db")
    _validate_runtime_secrets()  # must not raise


def test_allows_default_secret_in_debug(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", _DEFAULT_SECRET_KEY)
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://u@h:5432/db")
    _validate_runtime_secrets()  # must not raise


def test_rejects_default_secret_in_production(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", _DEFAULT_SECRET_KEY)
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://u@h:5432/db")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _validate_runtime_secrets()


def test_rejects_short_secret_in_production(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "too-short")
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://u@h:5432/db")
    with pytest.raises(RuntimeError):
        _validate_runtime_secrets()


def test_accepts_strong_secret_in_production(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "s" * 48)
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://u@h:5432/db")
    _validate_runtime_secrets()  # must not raise
