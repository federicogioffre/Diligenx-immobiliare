from datetime import datetime

from pydantic import BaseModel

from app.models.open_question import Priority


class MissingDocumentRead(BaseModel):
    id: int
    deal_id: int
    document_category: str
    expected_item: str
    reason: str
    priority: Priority
    created_at: datetime

    model_config = {"from_attributes": True}
