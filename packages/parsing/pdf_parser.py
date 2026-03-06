"""PDF text extraction — returns per-page text."""
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass
class PageText:
    page_number: int
    text: str


def extract_pdf(path: str | Path) -> list[PageText]:
    """Extract text from each page of a PDF file."""
    reader = PdfReader(str(path))
    pages: list[PageText] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(PageText(page_number=idx, text=text))
    return pages


def pdf_page_count(path: str | Path) -> int:
    reader = PdfReader(str(path))
    return len(reader.pages)
