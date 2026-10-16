"""Best-effort, expiring progress metadata. Never stores document content."""
import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
_last_publish: dict[tuple[int, int], float] = {}
_redis = None


def publish_progress(deal_id: int, run_id: int, done: int, total: int, document_id: int,
                     agent_name: str = "financial_analysis") -> None:
    global _redis
    from app.core.config import settings
    if not settings.REDIS_URL:
        return
    now = time.monotonic()
    key = (deal_id, run_id)
    if done != total and now - _last_publish.get(key, 0) < 2:
        return
    _last_publish[key] = now
    try:
        if _redis is None:
            from redis import Redis
            _redis = Redis.from_url(settings.REDIS_URL, socket_timeout=1, socket_connect_timeout=1)
        value = {"agent_name": agent_name, "run_id": run_id,
                 "completed_batches": done, "total_batches": total,
                 "document_id": document_id, "updated_at": datetime.now(timezone.utc).isoformat()}
        _redis.set(f"analysis-progress:{deal_id}", json.dumps(value), ex=settings.WORKER_JOB_TIMEOUT_SECONDS + 60)
    except Exception:
        logger.warning("Analysis progress temporarily unavailable for deal=%d", deal_id)


async def read_progress(pool, deal_id: int, run_id: int | None,
                        agent_name: str = "financial_analysis") -> dict | None:
    if pool is None or run_id is None:
        return None
    import asyncio
    try:
        raw = await asyncio.wait_for(pool.get(f"analysis-progress:{deal_id}"), timeout=1)
        data = json.loads(raw) if raw else None
        if (isinstance(data, dict) and data.get("run_id") == run_id
                and data.get("agent_name") == agent_name):
            return data
    except Exception:
        pass
    return None
