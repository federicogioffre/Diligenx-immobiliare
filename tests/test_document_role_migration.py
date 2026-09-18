"""Existing files remain generic and LOI roles survive migration round trips."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_role_migration_defaults_existing_and_future_rows_and_preserves_contents():
    path = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions/019_add_document_role.py"
    spec = importlib.util.spec_from_file_location("document_role_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE documents (id INTEGER PRIMARY KEY, filename TEXT, raw_text TEXT)"))
        connection.execute(sa.text("INSERT INTO documents VALUES (1, 'Legacy LOI.pdf', 'Preserved legacy text')"))
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            assert connection.execute(sa.text("SELECT document_role FROM documents WHERE id=1")).scalar_one() == "data_room"
            connection.execute(sa.text("INSERT INTO documents (id, filename) VALUES (2, 'New file.pdf')"))
            assert connection.execute(sa.text("SELECT document_role FROM documents WHERE id=2")).scalar_one() == "data_room"
            connection.execute(sa.text("UPDATE documents SET document_role='loi' WHERE id=1"))
            with pytest.raises(sa.exc.IntegrityError):
                connection.execute(sa.text("UPDATE documents SET document_role='contract' WHERE id=1"))
            with pytest.raises(sa.exc.IntegrityError):
                connection.execute(sa.text("UPDATE documents SET document_role=NULL WHERE id=1"))
            migration.downgrade()
            assert connection.execute(sa.text("SELECT filename, raw_text FROM documents WHERE id=1")).one() == (
                "Legacy LOI.pdf", "Preserved legacy text",
            )
            assert "document_role" not in {column["name"] for column in sa.inspect(connection).get_columns("documents")}
    engine.dispose()
