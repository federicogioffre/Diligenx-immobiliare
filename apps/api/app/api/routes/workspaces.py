from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.deal import Deal
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate, WorkspaceRead, WorkspaceUpdate
from app.services.auth import get_current_user

router = APIRouter()


def _owned_workspace_or_404(
    workspace_id: int,
    db: Session,
    current_user: User,
) -> Workspace:
    """Return the workspace iff it exists AND is owned by current_user.

    Returns 404 (not 403) on ownership mismatch to avoid leaking existence
    of workspaces belonging to other users.
    """
    ws = (
        db.query(Workspace)
        .filter(Workspace.id == workspace_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


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


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a single workspace by id (owner-scoped)."""
    return _owned_workspace_or_404(workspace_id, db, current_user)


@router.patch("/{workspace_id}", response_model=WorkspaceRead)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update name and/or description of a workspace."""
    ws = _owned_workspace_or_404(workspace_id, db, current_user)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(ws, key, value)
    db.commit()
    db.refresh(ws)
    return ws


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a workspace.

    Refuses with 409 if:
      - this is the user's last remaining workspace, or
      - the workspace still contains at least one deal
        (the user must clean it out first — we never cascade-delete deals
        from a workspace deletion).
    """
    ws = _owned_workspace_or_404(workspace_id, db, current_user)

    total = (
        db.query(Workspace)
        .filter(Workspace.owner_id == current_user.id)
        .count()
    )
    if total <= 1:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete your last workspace",
        )

    deals_count = (
        db.query(Deal).filter(Deal.workspace_id == workspace_id).count()
    )
    if deals_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Workspace contains {deals_count} deal(s). Delete them first.",
        )

    db.delete(ws)
    db.commit()
    # 204 → no body
