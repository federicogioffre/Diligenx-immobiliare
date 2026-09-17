"""Mandatory CI checks with the application's real, non-superuser pool."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.session import SessionLocal, engine
from app.db.tenant_context import clear_tenant_context, set_tenant_context
from app.models import User, Workspace, Deal
from app.models.document import Document, DocumentStatus


@pytest.fixture(scope="module")
def tenants():
    with engine.connect() as conn:
        role = conn.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
        assert not role.rolsuper and not role.rolbypassrls, "Run integration tests as the restricted app role"
    result = []
    for _ in range(2):
        with SessionLocal() as db:
            user = User(email=f"rls-{uuid.uuid4().hex}@example.com", hashed_password="unused", full_name="RLS")
            db.add(user)
            db.commit()
            uid = user.id
            set_tenant_context(db, uid)
            ws = Workspace(name="RLS workspace", owner_id=uid)
            db.add(ws)
            db.commit()
            deal = Deal(title="RLS deal", workspace_id=ws.id)
            db.add(deal)
            db.commit()
            doc = Document(deal_id=deal.id, filename="rls.txt", file_path="rls.txt", mime_type="text/plain", file_size=8, status=DocumentStatus.processed, raw_text="Evidence")
            db.add(doc)
            db.commit()
            result.append((uid, ws.id, deal.id, doc.id))
    return result


def test_tenant_survives_commits_rollbacks_and_different_connections(tenants):
    own, other = tenants
    engine.dispose()  # start with exactly one idle physical connection
    with SessionLocal() as db:
        set_tenant_context(db, own[0])
        original_pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
        db.commit()
        # Occupy the connection just returned; next transaction must rebind on
        # another physical connection, not accidentally rely on a stale GUC.
        with engine.connect() as occupied:
            occupied.execute(text("SELECT 1"))
            assert db.execute(text("SELECT pg_backend_pid()")).scalar_one() != original_pid
            for finish in (db.commit, db.rollback, db.commit):
                ids = db.execute(text("SELECT id FROM documents WHERE id IN (:a,:b)"), {"a": own[3], "b": other[3]}).scalars().all()
                assert ids == [own[3]]
                finish()
            db.execute(text("UPDATE documents SET raw_text='updated' WHERE id=:id"), {"id": own[3]})
            db.commit()
            assert db.get(Document, own[3]).raw_text == "updated"


def test_missing_cleared_and_reused_context_cannot_see_rows(tenants):
    with SessionLocal() as db:
        assert db.query(Document).count() == 0
        set_tenant_context(db, tenants[0][0])
        assert db.query(Document).count() == 1
        clear_tenant_context(db)
        assert db.query(Document).count() == 0
        db.commit()
        assert db.query(Document).count() == 0
    with SessionLocal() as fresh:
        assert fresh.query(Document).count() == 0


def test_cross_tenant_writes_refused_and_context_recovers_after_error(tenants):
    own, other = tenants
    with SessionLocal() as db:
        set_tenant_context(db, own[0])
        result = db.execute(text("UPDATE documents SET raw_text='intrusion' WHERE id=:id"), {"id": other[3]})
        assert result.rowcount == 0
        db.commit()
        with pytest.raises(DBAPIError):
            db.execute(text("INSERT INTO workspaces(name,owner_id) VALUES ('intrusion',:id)"), {"id": other[0]})
        db.rollback()
        assert db.query(Workspace).filter(Workspace.id == own[1]).one().owner_id == own[0]


def test_interleaved_sessions_keep_distinct_tenants(tenants):
    with SessionLocal() as a, SessionLocal() as b:
        set_tenant_context(a, tenants[0][0])
        set_tenant_context(b, tenants[1][0])
        for _ in range(3):
            assert [r.id for r in a.query(Deal)] == [tenants[0][2]]
            a.commit()
            assert [r.id for r in b.query(Deal)] == [tenants[1][2]]
            b.rollback()


def test_beta_database_guard_checks_real_role_policies_and_migration_head(monkeypatch):
    from app.core.config import settings
    from app.core.runtime_validation import validate_beta_database
    monkeypatch.setattr(settings, "BETA_MODE", True)
    validate_beta_database()
