"""Helpers shared by the real-estate stages: AgentRun lifecycle and document selection.

Every stage follows the engine's contract (``packages/agents/stage_tx``):
open the running ``AgentRun``, copy the inputs into plain values, commit
before the LLM phase, then delete the previous outputs and write the new
ones in a fresh transaction. On failure the stage marks its run failed and
re-raises; the orchestrator rolls the stage back and re-records the failure.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def open_run(db: Session, deal_id: int, agent_name: str):
    from app.models.agent_run import AgentRun, AgentRunStatus

    db.query(AgentRun).filter(
        AgentRun.deal_id == deal_id, AgentRun.agent_name == agent_name,
    ).delete(synchronize_session=False)
    db.flush()
    run = AgentRun(
        deal_id=deal_id,
        agent_name=agent_name,
        status=AgentRunStatus.running,
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()
    return run


def _duration(run) -> float:
    started = run.started_at
    if started is None:
        return 0.0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (run.completed_at - started).total_seconds()


def complete_run(db: Session, run, result: dict) -> None:
    from app.models.agent_run import AgentRunStatus

    run.completed_at = datetime.now(timezone.utc)
    run.status = AgentRunStatus.completed
    db.flush()
    logger.info("[%s] deal=%d — completed in %.2fs: %s",
                run.agent_name, run.deal_id, _duration(run), result)


def fail_run(db: Session, run, exc: BaseException) -> None:
    from app.models.agent_run import AgentRunStatus

    logger.exception("[%s] deal=%d — failed", run.agent_name, run.deal_id)
    run.completed_at = datetime.now(timezone.utc)
    run.status = AgentRunStatus.failed
    run.error_message = str(exc)[:2000]
    db.flush()


@lru_cache(maxsize=None)
def _keyword_pattern(keyword: str) -> re.Pattern:
    escaped = re.escape(keyword)
    tail = r"(?![a-zà-ù])" if len(keyword) <= 4 else ""
    return re.compile(rf"(?<![a-zà-ù]){escaped}{tail}")


def mentions_any(text: str, keywords) -> bool:
    lowered = text.lower()
    return any(_keyword_pattern(kw).search(lowered) for kw in keywords)


def haystack(doc, head_chars: int = 2000) -> str:
    filename = (doc.filename or "").lower().replace("_", " ").replace("-", " ")
    return filename + " " + (doc.raw_text or "")[:head_chars].lower()


def select_documents(
    db: Session,
    deal_id: int,
    *,
    document_ids: set[int] | None,
    routed_document_ids: set[int] | None,
    keywords,
) -> list:
    """Processed documents to analyse: routed ∪ keyword-detected.

    * ``document_ids=None``  → routing output unioned with keyword detection
    * ``document_ids=set()`` → nothing
    * ``document_ids={…}``   → exactly those (processed) documents
    """
    from app.models.document import Document, DocumentStatus

    if document_ids is not None and not document_ids:
        return []
    query = db.query(Document).filter(
        Document.deal_id == deal_id, Document.status == DocumentStatus.processed,
    )
    if document_ids is not None:
        query = query.filter(Document.id.in_(document_ids))
    docs = query.order_by(Document.id).all()
    if document_ids is None:
        routed = routed_document_ids or set()
        docs = [d for d in docs if d.id in routed or mentions_any(haystack(d), keywords)]
    return docs


def routed_ids(classifications: list[dict] | None, types) -> set[int]:
    wanted = set(types)
    return {
        c["document_id"] for c in (classifications or [])
        if c.get("document_type") in wanted
    }


def kinds_by_document(classifications: list[dict] | None) -> dict[int, str]:
    return {c["document_id"]: c.get("document_type") for c in (classifications or [])}
