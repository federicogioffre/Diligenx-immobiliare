from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.deal import Deal, DealStatus
from app.models.missing_document import MissingDocument
from app.models.red_flag import RedFlag, Severity
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.workspace import (
    CategoryCount,
    WorkspaceCreate,
    WorkspaceInsights,
    WorkspaceRead,
    WorkspaceUpdate,
)
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


@router.get("/{workspace_id}/insights", response_model=WorkspaceInsights)
def get_workspace_insights(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return aggregate metrics for the dashboard insights widget.

    All counts are scoped to the deals belonging to this workspace; the
    response always carries the full set of status/severity keys (zero-filled)
    so the frontend never has to handle missing buckets.
    """
    _owned_workspace_or_404(workspace_id, db, current_user)

    # ── Deals by status ──────────────────────────────────────────────── #
    status_rows = (
        db.query(Deal.status, func.count(Deal.id))
        .filter(Deal.workspace_id == workspace_id)
        .group_by(Deal.status)
        .all()
    )
    deals_by_status: dict[str, int] = {s.value: 0 for s in DealStatus}
    for status_value, count in status_rows:
        # SQLAlchemy returns the enum instance on PG and the raw string on SQLite.
        key = status_value.value if hasattr(status_value, "value") else str(status_value)
        deals_by_status[key] = count
    deals_total = sum(deals_by_status.values())
    deals_analyzed = sum(
        deals_by_status[s.value] for s in DealStatus if s != DealStatus.draft
    )

    # ── Red flags by severity ────────────────────────────────────────── #
    severity_rows = (
        db.query(RedFlag.severity, func.count(RedFlag.id))
        .join(Deal, RedFlag.deal_id == Deal.id)
        .filter(Deal.workspace_id == workspace_id)
        .group_by(RedFlag.severity)
        .all()
    )
    red_flags_by_severity: dict[str, int] = {s.value: 0 for s in Severity}
    for severity_value, count in severity_rows:
        key = severity_value.value if hasattr(severity_value, "value") else str(severity_value)
        red_flags_by_severity[key] = count
    red_flags_total = sum(red_flags_by_severity.values())

    # ── Top red flag categories (top 5) ──────────────────────────────── #
    category_rows = (
        db.query(RedFlag.category, func.count(RedFlag.id).label("count"))
        .join(Deal, RedFlag.deal_id == Deal.id)
        .filter(Deal.workspace_id == workspace_id)
        .group_by(RedFlag.category)
        .order_by(func.count(RedFlag.id).desc())
        .limit(5)
        .all()
    )
    top_red_flag_categories = [
        CategoryCount(category=cat, count=count) for cat, count in category_rows
    ]

    # ── Document completeness ────────────────────────────────────────── #
    deals_with_missing_documents = (
        db.query(MissingDocument.deal_id)
        .join(Deal, MissingDocument.deal_id == Deal.id)
        .filter(Deal.workspace_id == workspace_id)
        .distinct()
        .count()
    )

    return WorkspaceInsights(
        workspace_id=workspace_id,
        deals_total=deals_total,
        deals_by_status=deals_by_status,
        red_flags_total=red_flags_total,
        red_flags_by_severity=red_flags_by_severity,
        top_red_flag_categories=top_red_flag_categories,
        deals_analyzed=deals_analyzed,
        deals_with_missing_documents=deals_with_missing_documents,
    )
