"""The additive scope migration preserves existing deals without guessing targets."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_scope_migration_preserves_legacy_deals_and_roundtrips():
    path = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions/018_add_deal_target_company_names.py"
    spec = importlib.util.spec_from_file_location("scope_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE deals (id INTEGER PRIMARY KEY, title TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO deals (id, title) VALUES (1, 'Project codename')"))
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            row = connection.execute(text("SELECT title, target_company_names FROM deals WHERE id=1")).one()
            assert row == ("Project codename", None)
            connection.execute(text("UPDATE deals SET target_company_names=:scope WHERE id=1"),
                               {"scope": '["TargetCo S.p.A."]'})
            migration.downgrade()
        assert [column["name"] for column in inspect(connection).get_columns("deals")] == ["id", "title"]
        assert connection.execute(text("SELECT title FROM deals WHERE id=1")).scalar_one() == "Project codename"
    engine.dispose()
