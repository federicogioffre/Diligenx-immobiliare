from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.deal import Deal
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.deal import DealCreate, DealRead
from app.services.auth import get_current_user

router = APIRouter()


def _get_user_workspace(db: Session, workspace_id: int, user: User) -> Workspace:
    ws = (
        db.query(Workspace)
        .filter(Workspace.id == workspace_id, Workspace.owner_id == user.id)
        .first()
    )
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.get("/", response_model=list[DealRead])
def list_deals(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_workspace(db, workspace_id, current_user)
    return db.query(Deal).filter(Deal.workspace_id == workspace_id).all()


@router.post("/", response_model=DealRead, status_code=201)
def create_deal(
    workspace_id: int,
    payload: DealCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_workspace(db, workspace_id, current_user)
    deal = Deal(**payload.model_dump(), workspace_id=workspace_id)
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal


@router.get("/{deal_id}", response_model=DealRead)
def get_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal
