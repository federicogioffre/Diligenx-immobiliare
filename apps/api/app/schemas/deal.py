from datetime import datetime

from pydantic import BaseModel

from app.models.deal import DealStatus


class DealCreate(BaseModel):
    title: str
    description: str | None = None
    value: float | None = None


class DealUpdate(BaseModel):
    title: str | None = None
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


class DealAnalysisResponse(BaseModel):
    deal_id: int
    status: DealStatus
    completed: bool
    documents_analyzed: int
    clause_findings_count: int
    red_flags_count: int
    open_questions_count: int = 0
    report_id: int | None = None
    stages: dict | None = None


class CategoryImpact(BaseModel):
    category: str
    count: int
    impact: int
    max_severity: str  # "low" | "medium" | "high" | "critical"


class RiskDeductions(BaseModel):
    red_flags: dict
    observations: dict
    information_requests: dict
    missing_documents: dict


class RiskScoreResponse(BaseModel):
    deal_id: int
    score: int          # 0–100
    risk_level: str     # "low" | "medium" | "high" | "critical"
    deductions: RiskDeductions
    categories: list[CategoryImpact]


class DealQuestionRequest(BaseModel):
    question: str


class SourceReference(BaseModel):
    document_id: int
    page_number: int | None
    excerpt: str


class DealQuestionResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
