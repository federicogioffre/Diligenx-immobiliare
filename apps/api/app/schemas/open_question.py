from datetime import datetime

from pydantic import BaseModel

from app.models.open_question import Priority, QuestionStatus


class OpenQuestionRead(BaseModel):
    id: int
    deal_id: int
    document_id: int | None
    agent_name: str
    question: str
    priority: Priority
    status: QuestionStatus
    created_at: datetime

    model_config = {"from_attributes": True}
