from datetime import datetime

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.models.deal import DealStatus


CompanyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class TargetScope(BaseModel):
    target_company_names: list[CompanyName] | None = Field(default=None, max_length=20)

    @field_validator("target_company_names")
    @classmethod
    def distinct_names(cls, names):
        if names is None:
            return None
        seen = set()
        result = []
        for name in names:
            key = "".join(char for char in name.casefold() if char.isalnum())
            if not key or not any(char.isalnum() for char in key):
                raise ValueError("Inserisci una ragione sociale valida.")
            if key not in seen:
                seen.add(key)
                result.append(name)
        return result


class DealCreate(TargetScope):
    title: str
    description: str | None = None
    value: float | None = None


class DealUpdate(TargetScope):
    title: str | None = None
    description: str | None = None
    value: float | None = None
    report_language: str | None = None  # "it" | "en" | None (= auto-detect)


class DealRead(BaseModel):
    id: int
    workspace_id: int
    title: str
    description: str | None
    value: float | None
    status: DealStatus
    report_language: str | None
    target_company_names: list[str] | None = None
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
