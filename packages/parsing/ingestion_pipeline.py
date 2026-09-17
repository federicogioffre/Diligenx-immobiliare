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
    from packages.retrieval.embedding_service import get_embedding_provider

    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise ValueError(f"Document {document_id} not found")

    # Mark processing
    doc.status = DocumentStatus.processing
    mime_type, file_path = doc.mime_type, doc.file_path
    db.commit()

    try:
        extractor = _EXTRACTORS.get(mime_type)
        if extractor is None:
            raise ValueError(f"No extractor for MIME type: {mime_type}")

        from app.services.storage import open_local

        # --- Extract (download from cloud to temp file if needed) ---
        with open_local(file_path) as local_file:
            pages: list[PageText] = extractor(local_file)
            page_count_from_file = _get_page_count(mime_type, local_file)

        if not pages:
            raise ValueError("Document has no readable text; extraction is incomplete")

        if page_count_from_file is not None and len(pages) != page_count_from_file:
            raise ValueError("Not all PDF pages were extracted; document coverage is incomplete")
        if any(not page.text.strip() for page in pages):
            raise ValueError("A document page has no readable text; extraction is incomplete")

        # --- Full text & metadata ---
        full_text = "\n\n".join(p.text for p in pages)
        language = detect_language(full_text)

        # --- Chunk ---
        chunks = chunk_pages(pages)

        # Storage, OCR and the embedding request run without a DB connection.
        # Keep the old text/chunks intact until every new embedding is ready.
        provider = get_embedding_provider()
        embeddings = provider.embed_texts([c.text for c in chunks])
        if len(embeddings) != len(chunks):
            raise ValueError(
                f"Embedding count mismatch for document {document_id}: "
                f"{len(embeddings)} vectors for {len(chunks)} chunks"
            )
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc is None:
            raise ValueError(f"Document {document_id} was removed during ingestion")
        doc.raw_text = full_text
        doc.page_count = page_count_from_file or len(pages)
        doc.language = language

        # Remove any existing chunks (idempotent re-run). `synchronize_session=
        # "fetch"` ensures the deleted rows are also expunged from the session's
        # identity map; otherwise a subsequent INSERT that reuses a primary key
        # (common on SQLite, which recycles rowids when a table is emptied)
        # would collide with the stale instance.
        db.query(DocumentChunk).filter(
            DocumentChunk.document_id == doc.id
        ).delete(synchronize_session="fetch")

        for c, embedding in zip(chunks, embeddings):
            db.add(DocumentChunk(
                document_id=doc.id,
                chunk_index=c.chunk_index,
                content=c.text,
                page_number=c.page_number,
                token_count=c.token_count,
                embedding=embedding,
            ))

        doc.status = DocumentStatus.processed
        db.commit()

        logger.info(
            "Processed document %d: %d pages, %d chunks, %d embeddings, lang=%s",
            document_id, page_count_from_file or len(pages), len(chunks), len(embeddings), language,
        )

    except Exception:
        logger.exception("Failed to process document %d", document_id)
        db.rollback()
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.status = DocumentStatus.failed
            db.commit()
        raise
