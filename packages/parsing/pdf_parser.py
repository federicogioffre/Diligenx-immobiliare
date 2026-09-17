"""PDF text extraction — returns per-page text.

Native text extraction via pypdf; automatic OCR fallback for scanned/image-only
pages using pdf2image + pytesseract (requires Tesseract and poppler installed
on the system).
"""
import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

logger = logging.getLogger(__name__)

# Optional OCR dependencies — silently disabled if not installed.
try:
    from pdf2image import convert_from_path as _pdf2image_convert
    import pytesseract as _pytesseract
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False
    _pdf2image_convert = None  # type: ignore[assignment]
    _pytesseract = None  # type: ignore[assignment]


@dataclass
class PageText:
    page_number: int
    text: str


def _ocr_page(pdf_path: str, page_number: int) -> str:
    """OCR a single PDF page using pdf2image + pytesseract.

    Returns empty string if OCR libraries are not installed or if OCR fails.
    Uses 'ita+eng' language pack to cover both Italian and English documents.
    """
    if not _OCR_AVAILABLE:
        return ""
    try:
        images = _pdf2image_convert(
            pdf_path,
            first_page=page_number,
            last_page=page_number,
            dpi=300,
        )
        if not images:
            return ""
        return _pytesseract.image_to_string(images[0], lang="ita+eng")
    except Exception:
        logger.warning("OCR failed for page %d of %s", page_number, pdf_path)
        return ""


def extract_pdf(path: str | Path) -> list[PageText]:
    """Extract text from each page of a PDF file.

    For pages with no embedded text (scanned/image-only PDFs), falls back to
    OCR via pdf2image + pytesseract when available.
    """
    reader = PdfReader(str(path))
    pages: list[PageText] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if not text.strip():
            text = _ocr_page(str(path), idx)
        if not text.strip():
            raise ValueError(
                f"PDF page {idx} has no readable text after OCR; "
                "document coverage is incomplete"
            )
        pages.append(PageText(page_number=idx, text=text))
    return pages


def pdf_page_count(path: str | Path) -> int:
    reader = PdfReader(str(path))
    return len(reader.pages)
