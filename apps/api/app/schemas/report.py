from datetime import datetime

from pydantic import BaseModel

from app.models.report import ReportType, ReportStatus


class ReportRead(BaseModel):
    id: int
    deal_id: int
    report_type: ReportType
    title: str
    content: str | None
    status: ReportStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class ReportGenerateResponse(BaseModel):
    report_id: int
    deal_id: int
    markdown: str
    generation_available: bool = True
    stale: bool = False
