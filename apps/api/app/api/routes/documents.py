import logging
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile, File
from app.core.limiter import limiter
from typing import List
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal, get_db
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

# Max document ingestion pipelines running at once (see _run_ingestion).
_INGESTION_SLOTS = threading.BoundedSemaphore(4)


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


def _run_ingestion(document_id: int) -> None:
    """Run the full ingestion pipeline in a FRESH DB session.

    Intended to be scheduled via FastAPI BackgroundTasks so the HTTP
    response (201 Created) is returned to the client immediately, and
    any failure in parsing / OCR / embedding is isolated from the
    request lifecycle — the client never sees a 500 caused by ingestion.

    A separate SessionLocal is used because the request-scoped `db`
    dependency is closed as soon as the response is sent.

    Concurrency is capped by `_INGESTION_SLOTS`: each pipeline run holds a
    DB connection from start to finish (including slow embedding API
    calls), so an unbounded batch upload would exhaust the connection
    pool. The semaphore is acquired BEFORE opening the session, so queued
    ingestions wait without holding a connection.
    """
    from packages.parsing.ingestion_pipeline import process_document

    with _INGESTION_SLOTS:
        db = SessionLocal()
        try:
            process_document(document_id, db)
        except Exception:
            logger.exception("Background ingestion failed for document %d", document_id)
            # process_document already marks the doc as failed and commits before
            # re-raising, but be defensive in case the rollback/commit itself threw.
            try:
                db.rollback()
                doc = db.query(Document).filter(Document.id == document_id).first()
                if doc and doc.status != DocumentStatus.failed:
                    doc.status = DocumentStatus.failed
                    db.commit()
            except Exception:
                logger.exception(
                    "Could not persist failed state for document %d", document_id
                )
        finally:
            db.close()


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
@limiter.limit("30/minute")
async def upload_document(
    request: Request,
    deal_id: int,
    file: UploadFile,
    background_tasks: BackgroundTasks,
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

    # Schedule ingestion AFTER response is sent. Any failure inside the
    # pipeline (OCR on scanned PDFs, embedding errors, etc.) is isolated
    # from the HTTP response — the document will simply end in status=failed
    # and the UI will see it via the status polling.
    from app.services.jobs import enqueue_or_run
    await enqueue_or_run(
        request, background_tasks,
        "run_ingestion_for_document", _run_ingestion, doc.id,
    )
    return doc


@router.post("/upload-batch", response_model=list[DocumentUploadResponse], status_code=201)
def upload_documents_batch(
    deal_id: int,
    background_tasks: BackgroundTasks,
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

        background_tasks.add_task(_run_ingestion, doc.id)
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
