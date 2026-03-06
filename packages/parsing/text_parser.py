"""Plain text extraction."""
from pathlib import Path

from packages.parsing.pdf_parser import PageText


def extract_txt(path: str | Path) -> list[PageText]:
    """Read a plain text file. Treated as a single page."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return []
    return [PageText(page_number=1, text=text)]
