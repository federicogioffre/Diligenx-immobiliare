from pydantic import BaseModel
from typing import Optional


class DealPayload(BaseModel):
    title: str
    description: Optional[str] = None
    value: Optional[float] = None
    documents: list[str] = []


class DealAnalysisResult(BaseModel):
    summary: str
    score: float
    risks: list[str] = []
    opportunities: list[str] = []
