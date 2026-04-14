"""Document ingestion pipeline.

Extracts text from a file, detects language, splits into chunks,
generates embeddings, and stores everything in the database.
"""
import logging

from sqlalchemy.orm import Session

from packages.parsing.pdf_parser import PageText, extract_pdf, pdf_page_count
from packages.parsing.docx_parser import extract_docx
from packages.parsing.text_parser import extract_txt
from packages.parsing.language import detect_language
from packages.parsing.chunker import chunk_pages

logger = logging.getLogger(__name__)

# Maps MIME types to their extraction function
_EXTRACTORS: dict[str, callable] = {
    "application/pdf": extract_pdf,
    "text/plain": extract_txt,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": extract_docx,
}


def _get_page_count(mime_type: str, file_path: str) -> int | None:
    if mime_type == "application/pdf":
        return pdf_page_count(file_path)
    return None


def process_document(document_id: int, db: Session) -> None:
    """Run the full ingestion pipeline for a document.

    1. Load Document row from DB
    2. Extract per-page text (PDF / DOCX / TXT)
    3. Detect language
    4. Chunk text
    5. Store chunks in DocumentChunk table
    6. Generate embeddings for chunks
    7. Update Document status / metadata
    """
    # Import models here to keep packages/ decoupled from app/
    from app.models.document import Document, DocumentStatus
    from app.models.document_chunk import DocumentChunk
    from packages.retrieval.embedding_service import generate_embeddings_for_document

    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise ValueError(f"Document {document_id} not found")

    # Mark processing
    doc.status = DocumentStatus.processing
    db.commit()

    try:
        extractor = _EXTRACTORS.get(doc.mime_type)
        if extractor is None:
            raise ValueError(f"No extractor for MIME type: {doc.mime_type}")

        from app.services.storage import open_local

        # --- Extract (download from cloud to temp file if needed) ---
        with open_local(doc.file_path) as local_file:
            pages: list[PageText] = extractor(local_file)
            page_count_from_file = _get_page_count(doc.mime_type, local_file)

        if not pages:
            doc.status = DocumentStatus.processed
            doc.raw_text = ""
            doc.page_count = page_count_from_file or 0
            doc.language = "en"
            db.commit()
            return

        # --- Full text & metadata ---
        full_text = "\n\n".join(p.text for p in pages)
        doc.raw_text = full_text
        doc.page_count = page_count_from_file or len(pages)
        doc.language = detect_language(full_text)

        # --- Chunk ---
        chunks = chunk_pages(pages)

        # Remove any existing chunks (idempotent re-run)
        db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()

        for c in chunks:
            db.add(DocumentChunk(
                document_id=doc.id,
                chunk_index=c.chunk_index,
                content=c.text,
                page_number=c.page_number,
                token_count=c.token_count,
            ))

        db.flush()  # Ensure chunks have IDs before embedding step

        # --- Embeddings ---
        n_embedded = generate_embeddings_for_document(doc.id, db)

        doc.status = DocumentStatus.processed
        db.commit()

        logger.info(
            "Processed document %d: %d pages, %d chunks, %d embeddings, lang=%s",
            doc.id, doc.page_count, len(chunks), n_embedded, doc.language,
        )

    except Exception:
        logger.exception("Failed to process document %d", document_id)
        db.rollback()
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.status = DocumentStatus.failed
            db.commit()
        raise
