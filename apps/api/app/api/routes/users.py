"""Account self-service endpoints (GDPR arts. 15/17/20).

* ``GET  /users/me``         — who am I (art. 15, right of access)
* ``GET  /users/me/export``  — full structured export of the account's
  data as a downloadable JSON document (art. 20, data portability)
* ``DELETE /users/me``       — delete the account and every trace of its
  data: workspaces, deals, documents (DB rows AND stored files), findings,
  reports (art. 17, right to erasure)

The export contains all user-meaningful data: workspaces, deals, document
metadata, clause findings, red flags, open questions, missing documents,
company profiles and generated reports. It deliberately excludes
embeddings (derived, not portable) and the raw file binaries — the
original files are downloadable individually through the app while the
account is active.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes.auth import _clear_session_cookies
from app.core.limiter import limiter
from app.core.security import verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserRead
from app.services.auth import get_current_user
from app.services.storage import delete_file

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


@router.get("/me/export")
@limiter.limit("5/minute")
def export_my_data(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Assemble the account's full structured data as downloadable JSON."""
    from app.models.workspace import Workspace

    workspaces = (
        db.query(Workspace)
        .filter(Workspace.owner_id == current_user.id)
        .order_by(Workspace.id.asc())
        .all()
    )

    def _document(d) -> dict:
        return {
            "id": d.id,
            "filename": d.filename,
            "mime_type": d.mime_type,
            "file_size": d.file_size,
            "document_role": d.document_role,
            "status": d.status.value if d.status else None,
            "language": d.language,
            "page_count": d.page_count,
            "created_at": _iso(d.created_at),
            "clause_findings": [
                {
                    "clause_type": c.clause_type.value if c.clause_type else None,
                    "title": c.title,
                    "content": c.content,
                    "page_number": c.page_number,
                    "confidence": c.confidence,
                }
                for c in d.clause_findings
            ],
        }

    def _deal(deal) -> dict:
        return {
            "id": deal.id,
            "title": deal.title,
            "description": deal.description,
            "value": deal.value,
            "status": deal.status.value if deal.status else None,
            "report_language": deal.report_language,
            "created_at": _iso(deal.created_at),
            "documents": [_document(d) for d in deal.documents],
            "red_flags": [
                {
                    "title": f.title,
                    "issue": f.issue,
                    "risk": f.risk,
                    "recommendation": f.recommendation,
                    "severity": f.severity.value if f.severity else None,
                    "area": f.area.value if f.area else None,
                    "category": f.category,
                    "confidence": f.confidence,
                }
                for f in deal.red_flags
            ],
            "open_questions": [
                {
                    "question": q.question,
                    "status": q.status.value if q.status else None,
                    "priority": q.priority.value if q.priority else None,
                }
                for q in deal.open_questions
            ],
            "missing_documents": [
                {
                    "document_category": m.document_category,
                    "expected_item": m.expected_item,
                    "reason": m.reason,
                    "priority": m.priority.value if m.priority else None,
                }
                for m in deal.missing_documents
            ],
            "company_profiles": [
                {
                    "company_name": p.company_name,
                    "legal_form": p.legal_form,
                    "incorporation_date": p.incorporation_date,
                    "registered_office": p.registered_office,
                    "corporate_capital": p.corporate_capital,
                    "shareholders": p.shareholders,
                    "pledge": p.pledge,
                    "managing_body": p.managing_body,
                    "auditors": p.auditors,
                    "auditing_company": p.auditing_company,
                    "business": p.business,
                    "fiscal_year": p.fiscal_year,
                    "duration": p.duration,
                }
                for p in deal.company_profiles
            ],
            "reports": [
                {
                    "title": r.title,
                    "report_type": r.report_type.value if r.report_type else None,
                    "status": r.status.value if r.status else None,
                    "markdown": r.content,
                    "created_at": _iso(r.created_at),
                }
                for r in deal.reports
            ],
        }

    payload = {
        "export_format_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "created_at": _iso(current_user.created_at),
        },
        "workspaces": [
            {
                "id": w.id,
                "name": w.name,
                "created_at": _iso(w.created_at),
                "deals": [_deal(d) for d in w.deals],
            }
            for w in workspaces
        ],
    }

    from fastapi.responses import JSONResponse

    filename = f"diligenx_export_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


class AccountDeleteRequest(BaseModel):
    password: str


@router.delete("/me", status_code=204)
@limiter.limit("3/minute")
def delete_my_account(
    request: Request,
    response: Response,
    payload: AccountDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Erase the account and all its data (GDPR art. 17).

    Requires the current password in the body as a deliberate-action
    check — an XSS-hijacked session alone must not be able to wipe an
    account.

    Deletion order:
    1. stored files on R2/local (best-effort, per document)
    2. workspaces — the ORM cascades take deals, documents, chunks,
       findings, red flags, reports, agent runs, open questions,
       missing documents and company profiles with them
    3. the user row
    """
    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(status_code=403, detail="Password errata")

    from app.models.workspace import Workspace

    workspaces = (
        db.query(Workspace).filter(Workspace.owner_id == current_user.id).all()
    )

    files_deleted = 0
    for ws in workspaces:
        for deal in ws.deals:
            for doc in deal.documents:
                delete_file(doc.file_path)  # best-effort, never raises
                files_deleted += 1

    for ws in workspaces:
        db.delete(ws)  # cascades to deals and every child table

    user_id, user_email = current_user.id, current_user.email
    db.delete(current_user)
    db.commit()

    logger.info(
        "Account %d (%s) deleted on user request: %d workspaces, %d stored files",
        user_id, user_email, len(workspaces), files_deleted,
    )

    _clear_session_cookies(response)
