"""Tests for the Alembic connection URL resolution.

``Settings.migrations_database_url`` is what ``alembic/env.py`` migrates.
With Row-Level Security enforced, the app connects as ``diligenx_app``
(no DDL privileges) while migrations must run as the ``postgres`` owner:
``MIGRATIONS_DATABASE_URL`` carries that second URL and must win whenever
it is set, and be transparent (fall back to ``DATABASE_URL``) otherwise.
"""
from app.core.config import Settings, settings


def test_defaults_to_database_url_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "MIGRATIONS_DATABASE_URL", "")
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://app@h:5432/db")
    assert settings.migrations_database_url == "postgresql://app@h:5432/db"


def test_migrations_url_wins_when_set(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://diligenx_app@h:5432/db")
    monkeypatch.setattr(
        settings, "MIGRATIONS_DATABASE_URL", "postgresql://postgres@h:5432/db"
    )
    assert settings.migrations_database_url == "postgresql://postgres@h:5432/db"


def test_field_default_is_empty():
    """A fresh Settings (no env) must not force a separate migrations URL."""
    s = Settings(_env_file=None)
    assert s.MIGRATIONS_DATABASE_URL == ""
    assert s.migrations_database_url == s.DATABASE_URL


def test_alembic_env_uses_resolved_url():
    """env.py must read the resolved property, not DATABASE_URL directly."""
    src = open("alembic/env.py").read()
    assert "settings.migrations_database_url" in src
    assert 'set_main_option("sqlalchemy.url", settings.DATABASE_URL)' not in src
