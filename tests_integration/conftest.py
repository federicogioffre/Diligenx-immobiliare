"""Shared setup for the Postgres integration suite.

Unlike tests/conftest.py, this module does NOT force DATABASE_URL to SQLite.
These tests need a real Postgres connection so that app.db.session's
connection-pool lifecycle (checkin / pool_pre_ping) actually runs — the
sqlite-backed suite overrides get_db() with a fixture that bypasses the real
pool entirely, which is exactly why it never caught the incident this suite
guards against. See test_connection_pool_reuse.py for details.

DATABASE_URL must already be set to a Postgres DSN *before* pytest starts:
app.db.session builds its engine once, at import time.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
