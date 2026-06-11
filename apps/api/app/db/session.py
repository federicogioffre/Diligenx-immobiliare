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

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
