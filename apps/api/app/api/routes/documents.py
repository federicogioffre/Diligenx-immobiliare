import hashlib
import logging
import threading
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile, File
from app.core.limiter import limiter
from typing import List
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from slowapi.util import get_remote_address

from app.core.config import settings
from app.db.session import SessionLocal, get_db
from app.models.document import Document, DocumentStatus
from app.models.deal import Deal, DealStatus
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

# Max files accepted in a single /upload-batch request.
_MAX_BATCH_FILES = 50

# Chunk size for the bounded upload read.
_READ_CHUNK = 1024 * 1024  # 1 MiB


class _FileTooLarge(Exception):
    """Raised by _read_capped when an upload exceeds the configured limit."""


def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an upload fully, aborting as soon as it exceeds *max_bytes*.

    Reading the whole body with ``file.read()`` before checking its length
    lets a client exhaust memory with a multi-GB upload. Reading in bounded
    chunks and stopping at the limit caps memory at roughly *max_bytes*.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _FileTooLarge()
        chunks.append(chunk)
    return b"".join(chunks)


def _storage_key(deal_id: int, original_filename: str, content: bytes) -> str:
    """Stable key: retrying the same named file cannot create another document."""
    base = Path(original_filename).name  # strip any directory prefix
    hasher = hashlib.sha256(base.encode("utf-8") + b"\0")
    hasher.update(content)
    digest = hasher.hexdigest()
    return f"deals/{deal_id}/{digest}_{base}"


def _upload_user(request: Request, user: User = Depends(get_current_user)) -> User:
    # Dependencies run before the decorated route, so the limiter can use the
    # authenticated account instead of sharing a budget across an office IP.
    request.state.upload_user_id = user.id
    return user


def _upload_rate_key(request: Request) -> str:
    user_id = getattr(request.state, "upload_user_id", None)
    return f"upload-user:{user_id}" if user_id is not None else get_remote_address(request)


def _prepare_upload(deal_id: int, user_id: int, file: UploadFile, db: Session) -> DocumentUploadResponse:
    """Serialize changes to a deal's inventory; called outside the event loop.

    The PostgreSQL deal lock protects content-based idempotency across API
    replicas and serializes against the analysis claim and document deletion.
    A failed enqueue deliberately leaves the pending row for a safe retry.
    """
    deal = (
        db.query(Deal)
        .filter(Deal.id == deal_id, Deal.workspace.has(owner_id=user_id))
        .with_for_update()
        .populate_existing()
        .first()
    )
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")
    try:
        content = _read_capped(file, settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024)
    except _FileTooLarge:
        raise HTTPException(status_code=413, detail=f"File troppo grande. Massimo {settings.MAX_UPLOAD_SIZE_MB} MB")
    base_name = (file.filename or "unknown").replace("\\", "/").split("/")[-1]
    key = _storage_key(deal_id, base_name, content)
    doc = db.query(Document).filter(Document.deal_id == deal_id, Document.file_path == key).first()
    if doc is None:
        if deal.status == DealStatus.analyzing:
            raise HTTPException(status_code=409, detail="Analisi in corso: attendere prima di modificare i documenti.")
        save_file(content, key)
        doc = Document(
            deal_id=deal_id, filename=base_name, file_path=key,
            mime_type=file.content_type, file_size=len(content), status=DocumentStatus.pending,
        )
        db.add(doc)
        db.flush()
    elif doc.status == DocumentStatus.failed:
        if deal.status == DealStatus.analyzing:
            raise HTTPException(status_code=409, detail="Analisi in corso: attendere prima di riprovare il documento.")
        save_file(content, key)  # Also recover an object lost during a prior attempt.
        doc.status = DocumentStatus.pending
    response = DocumentUploadResponse.model_validate(doc)
    db.commit()
    return response


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


def _run_ingestion(document_id: int, user_id: int) -> None:
    """Run the full ingestion pipeline in a FRESH DB session.

    Intended to be scheduled via FastAPI BackgroundTasks so the HTTP
    response (201 Created) is returned to the client immediately, and
    any failure in parsing / OCR / embedding is isolated from the
    request lifecycle — the client never sees a 500 caused by ingestion.

    A separate SessionLocal is used because the request-scoped `db`
    dependency is closed as soon as the response is sent. *user_id* is
    the uploader; it binds the RLS tenant context on the fresh session so
    row-level policies apply to the background work exactly as they do
    inside a request handler.

    Concurrency is capped by `_INGESTION_SLOTS`: each pipeline run holds a
    DB connection from start to finish (including slow embedding API
    calls), so an unbounded batch upload would exhaust the connection
    pool. The semaphore is acquired BEFORE opening the session, so queued
    ingestions wait without holding a connection.
    """
    from app.db.tenant_context import set_tenant_context
    from packages.parsing.ingestion_pipeline import process_document

    with _INGESTION_SLOTS:
        db = SessionLocal()
        try:
            set_tenant_context(db, user_id)
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
@limiter.limit(lambda: settings.UPLOAD_RATE_LIMIT, key_func=_upload_rate_key)
async def upload_document(
    request: Request,
    deal_id: int,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(_upload_user),
):
    from app.services.jobs import enqueue_or_run

    user_id = current_user.id
    doc = await run_in_threadpool(_prepare_upload, deal_id, user_id, file, db)
    if doc.status in (DocumentStatus.pending, DocumentStatus.processing):
        await enqueue_or_run(
            request, background_tasks, "run_ingestion_for_document",
            _run_ingestion, doc.id, user_id, job_id=f"ingestion:{doc.id}",
        )
    return doc


@router.post("/upload-batch", response_model=list[DocumentUploadResponse], status_code=201)
@limiter.limit(lambda: settings.UPLOAD_BATCH_RATE_LIMIT, key_func=_upload_rate_key)
async def upload_documents_batch(
    request: Request,
    deal_id: int,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(_upload_user),
):
    """Save and durably dispatch each accepted file; retries reuse document IDs."""
    from app.services.jobs import enqueue_or_run

    if len(files) > _MAX_BATCH_FILES:
        raise HTTPException(status_code=413, detail=f"Too many files in one request. Maximum {_MAX_BATCH_FILES}.")
    user_id = current_user.id
    results = []
    for file in files:
        try:
            doc = await run_in_threadpool(_prepare_upload, deal_id, user_id, file, db)
        except HTTPException as exc:
            db.rollback()
            if exc.status_code in (400, 413):
                logger.warning("Skipping unsupported or oversized batch file: %s", file.filename)
                continue
            raise
        if doc.status in (DocumentStatus.pending, DocumentStatus.processing):
            await enqueue_or_run(
                request, background_tasks, "run_ingestion_for_document",
                _run_ingestion, doc.id, user_id, job_id=f"ingestion:{doc.id}",
            )
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

    deal = db.query(Deal).filter(Deal.id == doc.deal_id).with_for_update().populate_existing().one()
    if deal.status == DealStatus.analyzing:
        raise HTTPException(status_code=409, detail="Analisi in corso: attendere prima di eliminare documenti.")
    key = doc.file_path
    # Keep the inventory lock through deletion. A re-upload has the same
    # content key, and must not race with deletion of its newly stored object.
    delete_file(key)
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
