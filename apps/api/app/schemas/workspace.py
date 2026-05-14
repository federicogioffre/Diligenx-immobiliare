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


class CategoryCount(BaseModel):
    category: str
    count: int


class WorkspaceInsights(BaseModel):
    """Aggregate metrics for a single workspace, used by the insights dashboard."""

    workspace_id: int
    deals_total: int
    # Always contains all four DealStatus keys, even when zero, so the
    # frontend can render the pipeline widget without defensive checks.
    deals_by_status: dict[str, int]
    red_flags_total: int
    # Always contains all four Severity keys (low/medium/high/critical).
    red_flags_by_severity: dict[str, int]
    top_red_flag_categories: list[CategoryCount]
    # A deal is considered "analyzed" if it has progressed past draft. Used
    # by the frontend as the denominator for the completeness widget.
    deals_analyzed: int
    deals_with_missing_documents: int
