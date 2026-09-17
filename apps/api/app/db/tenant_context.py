"""Tenant identity belongs to the ORM session, never to a pooled connection.

Reapply a transaction-local GUC on every begin, including after commit/rollback.
The pool reset remains a second defence against legacy session-level bindings.
"""
from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.orm import Session

_TENANT_KEY = "diligenx_tenant_user_id"
_BIND = text("SELECT set_config('app.current_user_id', :uid, true)")


@event.listens_for(Session, "after_begin")
def _bind_transaction_tenant(session, transaction, connection):
    if connection.dialect.name == "postgresql":
        # Session.execute here would recurse while provisioning the connection.
        connection.execute(_BIND, {"uid": str(session.info.get(_TENANT_KEY, ""))})


def set_tenant_context(db: Session, user_id: int) -> None:
    """Bind this request/job until explicitly cleared; survives transaction ends."""
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise ValueError("Tenant user id must be a positive integer")
    db.info[_TENANT_KEY] = user_id
    # Authentication may already have started a transaction to read the user.
    db.connection().execute(_BIND, {"uid": str(user_id)})


def clear_tenant_context(db: Session) -> None:
    """Clear the current transaction and future transactions of this session."""
    db.info.pop(_TENANT_KEY, None)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.connection().execute(_BIND, {"uid": ""})
