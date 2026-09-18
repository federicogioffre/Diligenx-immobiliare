from datetime import datetime

from pydantic import BaseModel

from app.models.document import DocumentStatus
from app.services.document_readiness import ProcessingIssue


class DocumentRead(BaseModel):
    id: int
    deal_id: int
    filename: str
    mime_type: str
    file_size: int
    status: DocumentStatus
    analysis_ready: bool
    processing_issue: ProcessingIssue | None
    page_count: int | None
    language: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    id: int
    filename: str
    status: DocumentStatus
    file_size: int
    language: str | None

    model_config = {"from_attributes": True}
