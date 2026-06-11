from datetime import datetime

from pydantic import BaseModel


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
    created_at: datetime

    model_config = {"from_attributes": True}
