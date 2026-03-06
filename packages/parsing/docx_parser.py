"""DOCX text extraction."""
from pathlib import Path

from docx import Document as DocxDocument

from packages.parsing.pdf_parser import PageText


def extract_docx(path: str | Path) -> list[PageText]:
    """Extract text from a DOCX file.

    DOCX files don't have native page boundaries, so we treat the
    entire document as page 1.
    """
    doc = DocxDocument(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    full_text = "\n".join(paragraphs)
    if not full_text.strip():
        return []
    return [PageText(page_number=1, text=full_text)]
