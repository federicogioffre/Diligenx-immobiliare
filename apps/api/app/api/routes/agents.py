from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.session import get_db
from app.models.user import User
from app.models.deal import Deal
from app.services.auth import get_current_user

router = APIRouter()


class AnalyzeRequest(BaseModel):
    deal_id: int


class AnalyzeResponse(BaseModel):
    deal_id: int
    summary: str
    score: float


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_deal(
    payload: AnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deal = db.query(Deal).filter(Deal.id == payload.deal_id, Deal.user_id == current_user.id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    # Placeholder — replace with actual agent call from packages/agents
    summary = f"AI analysis for deal '{deal.title}': looks promising."
    score = 0.75

    deal.ai_summary = summary
    deal.ai_score = score
    db.commit()

    return AnalyzeResponse(deal_id=deal.id, summary=summary, score=score)
