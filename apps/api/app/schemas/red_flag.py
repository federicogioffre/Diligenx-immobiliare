from datetime import datetime

from pydantic import BaseModel

from app.models.red_flag import DueDiligenceArea, Severity


class RedFlagRead(BaseModel):
    id: int
    deal_id: int
    title: str
    # Issue / Risk / Recommendation triple — the structure of a professional
    # red-flag report entry. risk and recommendation are nullable because
    # rows produced before this schema (or by degraded LLM output) may only
    # carry the issue text.
    issue: str
    risk: str | None
    recommendation: str | None
    severity: Severity
    area: DueDiligenceArea | None
    category: str
    confidence: float | None
    source_document_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
