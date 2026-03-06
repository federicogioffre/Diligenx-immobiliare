import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.document import Document, DocumentStatus
from app.models.deal import Deal
from app.models.user import User
from app.schemas.document import DocumentRead, DocumentUploadResponse
from app.services.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=201,
)
def upload_document(
    deal_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify deal exists and belongs to user's workspace
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Deal.workspace.has(owner_id=current_user.id))
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}",
        )

    # Read file content
    content = file.file.read()
    file_size = len(content)

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    # Save to disk
    upload_dir = Path(settings.UPLOAD_DIR) / str(deal_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    file_path = upload_dir / safe_name

    with open(file_path, "wb") as f:
        f.write(content)

    doc = Document(
        deal_id=deal_id,
        filename=file.filename or "unknown",
        file_path=str(file_path),
        mime_type=file.content_type or "application/octet-stream",
        file_size=file_size,
        status=DocumentStatus.pending,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Trigger ingestion pipeline
    from packages.parsing.ingestion_pipeline import process_document

    try:
        process_document(doc.id, db)
        db.refresh(doc)
    except Exception:
        logger.exception("Ingestion failed for document %d", doc.id)
        # Document is already marked as 'failed' by the pipeline;
        # refresh so the response reflects the actual status.
        db.refresh(doc)

    return doc


@router.get(
    "/deals/{deal_id}/documents",
    response_model=list[DocumentRead],
)
def list_deal_documents(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Deal.workspace.has(owner_id=current_user.id))
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    docs = db.query(Document).filter(Document.deal_id == deal_id).all()
    return docs
