import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from app.core.limiter import limiter
from typing import List
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.document import Document, DocumentStatus
from app.models.deal import Deal
from app.models.user import User
from app.schemas.document import DocumentRead, DocumentUploadResponse
from app.services.auth import get_current_user
from app.services.storage import save_file, delete_file

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _storage_key(deal_id: int, original_filename: str) -> str:
    """Build a unique storage key (used as both the S3 object key and local sub-path)."""
    base = Path(original_filename).name  # strip any directory prefix
    return f"deals/{deal_id}/{uuid.uuid4().hex}_{base}"


def _assert_deal_access(deal_id: int, user_id: int, db: Session) -> Deal:
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Deal.workspace.has(owner_id=user_id))
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


def _ingest(doc: Document, db: Session) -> None:
    """Run the ingestion pipeline; swallow exceptions (document already marked failed)."""
    from packages.parsing.ingestion_pipeline import process_document
    try:
        process_document(doc.id, db)
        db.refresh(doc)
    except Exception:
        logger.exception("Ingestion failed for document %d", doc.id)
        db.refresh(doc)


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
@limiter.limit("30/minute")
def upload_document(
    request: Request,
    deal_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _assert_deal_access(deal_id, current_user.id, db)

    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    content = file.file.read()
    file_size = len(content)

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        raise HTTPException(status_code=400, detail=f"File troppo grande. Massimo {settings.MAX_UPLOAD_SIZE_MB} MB")

    base_name = (file.filename or "unknown").replace("\\", "/").split("/")[-1]
    key = _storage_key(deal_id, base_name)
    save_file(content, key)

    doc = Document(
        deal_id=deal_id,
        filename=base_name,
        file_path=key,          # stores the storage key (works for both local and cloud)
        mime_type=file.content_type or "application/octet-stream",
        file_size=file_size,
        status=DocumentStatus.pending,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    _ingest(doc, db)
    return doc


@router.post("/upload-batch", response_model=list[DocumentUploadResponse], status_code=201)
def upload_documents_batch(
    deal_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload multiple documents in a single request."""
    _assert_deal_access(deal_id, current_user.id, db)

    results = []
    for file in files:
        if file.content_type not in ALLOWED_MIME_TYPES:
            logger.warning("Skipping unsupported type %s: %s", file.filename, file.content_type)
            continue

        content = file.file.read()
        file_size = len(content)
        if file_size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            logger.warning("Skipping oversized file %s (%d bytes)", file.filename, file_size)
            continue

        base_name = (file.filename or "unknown").replace("\\", "/").split("/")[-1]
        key = _storage_key(deal_id, base_name)
        save_file(content, key)

        doc = Document(
            deal_id=deal_id,
            filename=base_name,
            file_path=key,
            mime_type=file.content_type or "application/octet-stream",
            file_size=file_size,
            status=DocumentStatus.pending,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        _ingest(doc, db)
        results.append(doc)

    return results


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = (
        db.query(Document)
        .join(Document.deal)
        .join(Deal.workspace)
        .filter(
            Document.id == document_id,
            Deal.workspace.has(owner_id=current_user.id),
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    delete_file(doc.file_path)   # best-effort, never raises

    db.delete(doc)
    db.commit()


@router.get("/deals/{deal_id}/documents", response_model=list[DocumentRead])
def list_deal_documents(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _assert_deal_access(deal_id, current_user.id, db)
    return db.query(Document).filter(Document.deal_id == deal_id).all()
