from datetime import datetime

from pydantic import BaseModel


class WorkspaceCreate(BaseModel):
    name: str
    description: str | None = None


class WorkspaceUpdate(BaseModel):
    """Partial update payload. All fields optional; only provided fields are applied."""

    name: str | None = None
    description: str | None = None


class WorkspaceRead(BaseModel):
    id: int
    name: str
    description: str | None
    owner_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
