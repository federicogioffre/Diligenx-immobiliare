from datetime import datetime

from pydantic import BaseModel

from app.models.red_flag import Severity


class RedFlagRead(BaseModel):
    id: int
    deal_id: int
    title: str
    description: str
    severity: Severity
    category: str
    confidence: float | None
    source_document_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
