"""Reconcile an interrupted analysis only after its process/job is inactive."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.tenant_context import set_tenant_context
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.deal import Deal, DealStatus


def utc_timestamp(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def mark_analysis_failed(
    db: Session,
    deal_id: int,
    user_id: int,
    reason: str,
    *,
    expected_admission: datetime | None = None,
    invocation_started_at: datetime | None = None,
) -> bool:
    """Mark the current interrupted run failed, preserving committed outputs.

    The caller MUST first reap its child, or (for maintenance) confirm that
    Redis has no active/queued job. This helper does not cancel any work.
    It flushes but does not commit: the caller owns the transaction.

    A worker supplies its captured admission timestamp and invocation cutoff.
    Both are checked under the deal lock, so delayed cleanup cannot downgrade
    an already completed analysis or a more recently admitted run.
    """
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("Tenant user id must be a positive integer")
    set_tenant_context(db, user_id)
    deal = (
        db.query(Deal)
        .filter(Deal.id == deal_id, Deal.workspace.has(owner_id=user_id))
        .with_for_update()
        .populate_existing()
        .first()
    )
    if deal is None or deal.status != DealStatus.analyzing:
        return False

    admission = deal.updated_at or deal.created_at
    if expected_admission is not None and utc_timestamp(admission) != utc_timestamp(expected_admission):
        return False
    if invocation_started_at is not None and utc_timestamp(admission) > utc_timestamp(invocation_started_at):
        return False

    finished_at = datetime.now(timezone.utc)
    runs = db.query(AgentRun).filter(
        AgentRun.deal_id == deal_id,
        AgentRun.status == AgentRunStatus.running,
        # Do not relabel historical runs from an earlier admission.
        or_(AgentRun.started_at >= admission,
            (AgentRun.started_at.is_(None)) & (AgentRun.created_at >= admission)),
    ).all()
    for run in runs:
        run.status = AgentRunStatus.failed
        run.completed_at = finished_at
        run.error_message = reason[:2000]
    deal.status = DealStatus.draft
    db.flush()
    return True
