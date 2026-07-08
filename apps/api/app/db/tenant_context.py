"""Per-request tenant context for Postgres Row-Level Security.

The RLS policies installed by migration 008 read ``app.current_user_id`` from
the session. This module exposes a single helper, :func:`set_tenant_context`,
which writes that GUC at the session level so Postgres applies the policies
to every query on the connection — including queries that span multiple
transactions (e.g. the analysis pipeline, which commits between stages).

Connection-pool safety: a SQLAlchemy ``checkin`` event registered in
``app.db.session`` issues ``RESET app.current_user_id`` whenever a connection
is returned to the pool, so a connection never leaks a stale tenant context
to the next request that picks it up.

On SQLite (test environment) the function is a no-op — SQLite has no RLS and
the GUC syntax would error.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def set_tenant_context(db: Session, user_id: int) -> None:
    """Bind *user_id* as the tenant context on this session's connection.

    Applies to every subsequent query until either ``clear_tenant_context``
    is called, or the connection is returned to the pool (where it is
    automatically reset).

    Idempotent: calling twice with the same user is harmless; calling with
    a different user swaps the context.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return

    # SET (without LOCAL) applies to the connection until reset, so it
    # survives the multiple ``db.commit()`` calls a pipeline stage performs.
    db.execute(text("SET app.current_user_id = :uid"), {"uid": str(user_id)})


def clear_tenant_context(db: Session) -> None:
    """Reset the tenant GUC, hiding all tenant-scoped rows from subsequent
    queries on this connection. Mostly useful in tests; the pool ``checkin``
    hook clears it automatically when a connection is released.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    db.execute(text("RESET app.current_user_id"))
