from datetime import datetime

from pydantic import BaseModel

from app.models.agent_run import AgentRunStatus


class AgentRunRead(BaseModel):
    """Read schema for a single agent execution record.

    ``duration_seconds`` is derived from ``started_at`` / ``completed_at``
    via the Python property on :class:`~app.models.agent_run.AgentRun`;
    it is ``None`` for runs that have not yet completed.
    """

    id: int
    deal_id: int
    document_id: int | None
    agent_name: str
    status: AgentRunStatus
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None
    error_message: str | None
    input_hash: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
