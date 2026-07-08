import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", tags=["health"])
def health(response: Response, db: Session = Depends(get_db)):
    """Liveness + readiness probe.

    Verifies the database connection with a trivial query so that
    monitoring (Railway health checks, uptime probes) catches a
    DB-outage state instead of reporting a green API in front of a
    dead database. Returns 503 with a degraded body when the DB is
    unreachable — kept intentionally vague to avoid leaking internals.
    """
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}
    except Exception:
        logger.exception("Health check: database unreachable")
        response.status_code = 503
        return {"status": "degraded", "database": "unreachable"}
