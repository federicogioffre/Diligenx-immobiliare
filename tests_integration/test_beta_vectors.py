"""Execute pgvector retrieval and legacy migration on real PostgreSQL."""
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import Mock
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.db.session import SessionLocal
from app.db.tenant_context import set_tenant_context
from app.models import User, Workspace, Deal
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk, EMBEDDING_DIM
from packages.retrieval.retrieval_service import search_similar_chunks


def vector(x, y):
    return [float(x), float(y)] + [0.0] * (EMBEDDING_DIM - 2)


def test_postgres_retrieval_orders_limits_and_excludes_foreign_or_failed_documents():
    owners = []
    document_ids = []
    try:
        for index in range(2):
            with SessionLocal() as db:
                user = User(email=f"vectors-{uuid.uuid4().hex}@example.com",
                            hashed_password="unused", full_name="Vectors")
                db.add(user)
                db.commit()
                owner_id = user.id
                owners.append(owner_id)
                set_tenant_context(db, owner_id)
                workspace = Workspace(name="Vector test", owner_id=owner_id)
                db.add(workspace)
                db.flush()
                deal = Deal(title="Vector test", workspace_id=workspace.id)
                db.add(deal)
                db.flush()
                deal_id = deal.id
                ids = []
                for position, (embedding, status) in enumerate([
                    (vector(0, 1), DocumentStatus.processed),
                    (vector(1, 0), DocumentStatus.processed),
                    (vector(0.8, 0.2), DocumentStatus.processed),
                    (vector(1, 0), DocumentStatus.failed),
                ]):
                    doc = Document(deal_id=deal_id, filename=f"{position}.txt",
                                   file_path=f"{position}.txt", mime_type="text/plain",
                                   file_size=8, status=status)
                    db.add(doc)
                    db.flush()
                    ids.append(doc.id)
                    db.add(DocumentChunk(document_id=doc.id, chunk_index=0,
                                         content=f"tenant-{index}-document-{position}",
                                         page_number=1, embedding=embedding))
                db.commit()
                document_ids.append((deal_id, ids))
        provider = Mock()
        provider.embed_texts.return_value = [vector(1, 0)]
        with SessionLocal() as db:
            set_tenant_context(db, owners[0])
            result = search_similar_chunks(document_ids[0][0], "evidence", db,
                                           top_k=2, provider=provider)
            assert [match.document_id for match in result] == document_ids[0][1][1:3]
            assert [match.score for match in result] == [1.0, 0.9701]
            assert search_similar_chunks(document_ids[1][0], "evidence", db,
                                          provider=provider) == []
    finally:
        for owner_id in owners:
            with SessionLocal() as db:
                set_tenant_context(db, owner_id)
                for workspace in db.query(Workspace).filter(Workspace.owner_id == owner_id):
                    db.delete(workspace)
                db.commit()
                db.query(User).filter(User.id == owner_id).delete()
                db.commit()


@pytest.fixture
def migration_connection():
    # A temporary table shadows the real table, so migration round trips do
    # not change the shared application's schema or any tenant's data.
    engine = create_engine(os.environ["MIGRATIONS_DATABASE_URL"])
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TEMP TABLE document_chunks (embedding TEXT) ON COMMIT DROP"
            ))
            yield connection
    finally:
        engine.dispose()


def migration_module():
    path = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions/017_use_native_pgvector_embeddings.py"
    spec = importlib.util.spec_from_file_location("vector_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_embedding_conversion_and_downgrade_preserve_values(migration_connection):
    connection = migration_connection
    original = vector(1, 0)
    connection.execute(text("INSERT INTO document_chunks VALUES (:embedding), (NULL)"),
                       {"embedding": json.dumps(original)})
    with Operations.context(MigrationContext.configure(connection)):
        migration_module().upgrade()
        assert connection.execute(text(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid='pg_temp.document_chunks'::regclass AND attname='embedding'"
        )).scalar_one() == "vector(1536)"
        stored = connection.execute(text(
            "SELECT embedding::text FROM document_chunks WHERE embedding IS NOT NULL"
        )).scalar_one()
        assert json.loads(stored) == original
        assert connection.execute(text(
            "SELECT count(*) FROM document_chunks WHERE embedding IS NULL"
        )).scalar_one() == 1
        migration_module().downgrade()
        assert connection.execute(text(
            "SELECT pg_typeof(embedding)::text FROM document_chunks LIMIT 1"
        )).scalar_one() == "text"
        stored = connection.execute(text(
            "SELECT embedding FROM document_chunks WHERE embedding IS NOT NULL"
        )).scalar_one()
        assert json.loads(stored) == original


def test_invalid_legacy_embedding_aborts_without_discarding_data(migration_connection):
    connection = migration_connection
    connection.execute(text("INSERT INTO document_chunks VALUES ('[1,2]')"))
    with pytest.raises(DBAPIError):
        with connection.begin_nested():
            with Operations.context(MigrationContext.configure(connection)):
                migration_module().upgrade()
    assert connection.execute(text("SELECT embedding FROM document_chunks")).scalar_one() == "[1,2]"
    assert connection.execute(text(
        "SELECT pg_typeof(embedding)::text FROM document_chunks"
    )).scalar_one() == "text"
