from datetime import datetime

from pydantic import BaseModel

from app.models.clause_finding import ClauseType


class ClauseFindingRead(BaseModel):
    id: int
    document_id: int
    clause_type: ClauseType
    title: str
    content: str
    page_number: int | None
    confidence: float | None
    created_at: datetime

    model_config = {"from_attributes": True}
