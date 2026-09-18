from datetime import datetime

from pydantic import BaseModel, Field


class CompanyFieldSource(BaseModel):
    value: str
    source_document_ids: list[int] = Field(default_factory=list)
    source_filenames: list[str] = Field(default_factory=list)
    profile_ids: list[int] = Field(default_factory=list)


class CompanyProfileRead(BaseModel):
    id: int
    deal_id: int

    company_name: str
    legal_form: str | None
    incorporation_date: str | None
    registered_office: str | None
    corporate_capital: str | None
    shareholders: str | None
    pledge: str | None
    managing_body: str | None
    auditors: str | None
    auditing_company: str | None
    business: str | None
    fiscal_year: str | None
    duration: str | None

    confidence: float | None
    source_document_id: int | None
    source_document_ids: list[int] = Field(default_factory=list)
    source_filenames: list[str] = Field(default_factory=list)
    conflicting_fields: list[str] = Field(default_factory=list)
    field_sources: dict[str, list[CompanyFieldSource]] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}
