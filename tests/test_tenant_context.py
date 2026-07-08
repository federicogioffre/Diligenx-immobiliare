"""Unit tests for the RLS tenant-context wiring.

The real enforcement tests live in test_rls_isolation.py and need a real
Postgres with a non-superuser role (opt-in via RLS_TEST_DATABASE_URL).
These tests run on the default SQLite suite and verify:

* the helpers are silent no-ops on SQLite (no GUC syntax errors)
* the background-task entry points accept and forward user_id
* get_current_user binds the context (smoke: it doesn't blow up on SQLite)
"""
import inspect

from app.db.tenant_context import clear_tenant_context, set_tenant_context


class TestSqliteNoOp:

    def test_set_is_noop_on_sqlite(self, db):
        # Must not raise: SQLite has no SET/GUC syntax.
        set_tenant_context(db, 12345)

    def test_clear_is_noop_on_sqlite(self, db):
        clear_tenant_context(db)

    def test_authenticated_request_works_on_sqlite(self, client, auth_headers):
        # get_current_user calls set_tenant_context on every request; the
        # suite runs on SQLite, so this exercises the no-op path end-to-end.
        assert client.get("/users/me", headers=auth_headers).status_code == 200


class TestBackgroundTaskSignatures:
    """The user_id must flow to every fresh-session background entry point.

    Signature checks: cheap insurance that a refactor doesn't silently
    drop the tenant argument from one of the four paths (BackgroundTasks
    ingestion, BackgroundTasks pipeline, Arq ingestion, Arq pipeline).
    """

    def test_run_ingestion_takes_user_id(self):
        from app.api.routes.documents import _run_ingestion
        assert list(inspect.signature(_run_ingestion).parameters) == [
            "document_id", "user_id",
        ]

    def test_run_pipeline_background_takes_user_id(self):
        from app.api.routes.deals import _run_pipeline_background
        assert list(inspect.signature(_run_pipeline_background).parameters) == [
            "deal_id", "user_id",
        ]

    def test_arq_pipeline_task_takes_user_id(self):
        from app.worker import run_pipeline_for_deal
        assert list(inspect.signature(run_pipeline_for_deal).parameters) == [
            "ctx", "deal_id", "user_id",
        ]

    def test_arq_ingestion_task_takes_user_id(self):
        from app.worker import run_ingestion_for_document
        assert list(inspect.signature(run_ingestion_for_document).parameters) == [
            "ctx", "document_id", "user_id",
        ]
