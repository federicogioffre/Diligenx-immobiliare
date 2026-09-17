import logging
import asyncio

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", tags=["health"])
async def health(request: Request, response: Response, db: Session = Depends(get_db)):
    """Liveness + readiness probe.

    Verifies the database connection with a trivial query so that
    monitoring (Railway health checks, uptime probes) catches a
    DB-outage state instead of reporting a green API in front of a
    dead database. Returns 503 with a degraded body when the DB is
    unreachable — kept intentionally vague to avoid leaking internals.
    """
    try:
        db.execute(text("SELECT 1"))
        db.rollback()  # release the connection before waiting for Redis
    except Exception:
        logger.exception("Health check: database unreachable")
        response.status_code = 503
        return {"status": "degraded", "database": "unreachable"}

    from app.core.config import settings
    if settings.REDIS_URL:
        pool = getattr(request.app.state, "arq_pool", None)
        try:
            if pool is None:
                raise ConnectionError("Queue unavailable")
            await asyncio.wait_for(pool.ping(), timeout=2)
            worker_alive = bool(await asyncio.wait_for(
                pool.exists("arq:queue:health-check"), timeout=2,
            ))
        except Exception:
            response.status_code = 503
            return {"status": "degraded", "database": "ok", "queue": "unreachable"}
        if not worker_alive:
            response.status_code = 503
            return {"status": "degraded", "database": "ok", "queue": "ok", "worker": "unavailable"}
        return {"status": "ok", "database": "ok", "queue": "ok", "worker": "ok"}
    return {"status": "ok", "database": "ok"}
