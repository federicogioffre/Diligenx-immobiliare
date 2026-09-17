"""DOCX text extraction."""
from pathlib import Path

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from packages.parsing.pdf_parser import PageText


def _body_text(parent, element) -> list[str]:
    """Traverse paragraphs and tables in their original XML order."""
    parts: list[str] = []
    for child in element:
        if child.tag.endswith("}p"):
            text = Paragraph(child, parent).text
            if text.strip():
                parts.append(text)
        elif child.tag.endswith("}tbl"):
            table = Table(child, parent)
            seen_cells = set()
            for row in table.rows:
                cells = []
                for cell in row.cells:
                    # A merged cell appears repeatedly in row.cells.
                    if cell._tc in seen_cells:
                        continue
                    seen_cells.add(cell._tc)
                    cells.append("\n".join(_body_text(cell, cell._tc)))
                if any(cells):
                    parts.append(" | ".join(cells))
    return parts


def extract_docx(path: str | Path) -> list[PageText]:
    """Extract text from a DOCX file.

    DOCX files don't have native page boundaries, so we treat the
    entire document as page 1.
    """
    doc = DocxDocument(str(path))
    full_text = "\n".join(_body_text(doc, doc.element.body))
    if not full_text.strip():
        return []
    return [PageText(page_number=1, text=full_text)]
