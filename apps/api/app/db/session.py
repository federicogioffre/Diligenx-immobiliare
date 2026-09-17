from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

connect_args: dict = {}
engine_kwargs: dict = {"pool_pre_ping": True}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
else:
    # Background ingestion tasks each hold a connection for the whole
    # pipeline run (including slow embedding API calls), so the default
    # pool (5 + 10 overflow) exhausts during batch uploads while the
    # frontend polls the document list.
    engine_kwargs.update(pool_size=10, max_overflow=20, pool_timeout=60)
    # Managed Postgres sits behind a TCP proxy that drops connections which
    # stay silent for minutes (the analysis pipeline waits on the LLM for
    # far longer than that). Keepalives keep the path alive; recycling caps
    # how old a pooled connection may get before it is reopened.
    connect_args.update(
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )
    engine_kwargs.update(pool_recycle=1800)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    **engine_kwargs,
)

# Enable WAL mode + generous busy-timeout for SQLite so that long-running
# background analysis (which holds write locks while making LLM calls) does
# not block concurrent HTTP polling requests.
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")   # readers never block writers
        cursor.execute("PRAGMA busy_timeout=30000")  # wait up to 30 s on lock
        cursor.close()

# RLS tenant context: clear ``app.current_user_id`` whenever a Postgres
# connection is returned to the pool, so a subsequent request can never
# inherit a stale tenant context. ``set_tenant_context`` rebinds the GUC
# at the start of each authenticated request / background job.
if engine.dialect.name == "postgresql":
    @event.listens_for(engine, "checkin")
    def _reset_tenant_context(dbapi_conn, _record):  # noqa: ANN001
        try:
            cursor = dbapi_conn.cursor()
            cursor.execute("RESET app.current_user_id")
            cursor.close()
            # psycopg2 opened an implicit transaction for the RESET above.
            # Commit it so the connection is returned to the pool with no
            # open transaction — otherwise the next checkout's pool_pre_ping
            # (which sets autocommit=True) raises "set_session cannot be used
            # inside a transaction", 500-ing every reused connection.
            # Commit (not rollback) so the RESET itself persists.
            dbapi_conn.commit()
        except Exception:
            # Don't propagate — the pool will discard a broken connection
            # on the next checkout / ping.
            try:
                dbapi_conn.rollback()
            except Exception:
                pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
