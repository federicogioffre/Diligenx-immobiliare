from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate, WorkspaceRead
from app.services.auth import get_current_user

router = APIRouter()


@router.get("/", response_model=list[WorkspaceRead])
def list_workspaces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all workspaces owned by the current user."""
    return (
        db.query(Workspace)
        .filter(Workspace.owner_id == current_user.id)
        .all()
    )


@router.post("/", response_model=WorkspaceRead, status_code=201)
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new workspace owned by the current user."""
    ws = Workspace(**payload.model_dump(), owner_id=current_user.id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws
