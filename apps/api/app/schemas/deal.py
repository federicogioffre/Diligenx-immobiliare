from datetime import datetime

from pydantic import BaseModel

from app.models.deal import DealStatus


class DealCreate(BaseModel):
    title: str
    description: str | None = None
    value: float | None = None


class DealRead(BaseModel):
    id: int
    workspace_id: int
    title: str
    description: str | None
    value: float | None
    status: DealStatus
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}
