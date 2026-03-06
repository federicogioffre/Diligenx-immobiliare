"""Split document pages into overlapping text chunks."""
from dataclasses import dataclass

from packages.parsing.pdf_parser import PageText

# Defaults tuned for Claude's context window
DEFAULT_CHUNK_SIZE = 1000  # characters per chunk
DEFAULT_CHUNK_OVERLAP = 200  # overlap between consecutive chunks


@dataclass
class Chunk:
    chunk_index: int
    page_number: int | None
    text: str
    token_count: int


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English/Italian."""
    return max(1, len(text) // 4)


def chunk_pages(
    pages: list[PageText],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split a list of page texts into overlapping chunks.

    Each chunk records the page_number it originates from.
    When a chunk spans a page boundary, the page_number of the
    starting page is used.
    """
    chunks: list[Chunk] = []
    idx = 0

    for page in pages:
        text = page.text
        start = 0

        while start < len(text):
            end = start + chunk_size

            # Try to break at a sentence/paragraph boundary
            if end < len(text):
                # Look for a good break point within the last 20% of the chunk
                search_start = max(start, end - chunk_size // 5)
                for sep in ("\n\n", "\n", ". ", "? ", "! "):
                    pos = text.rfind(sep, search_start, end)
                    if pos != -1:
                        end = pos + len(sep)
                        break

            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(Chunk(
                    chunk_index=idx,
                    page_number=page.page_number,
                    text=chunk_text,
                    token_count=_estimate_tokens(chunk_text),
                ))
                idx += 1

            start = end - chunk_overlap
            if start <= (end - chunk_size):
                # Avoid infinite loop if overlap >= chunk_size
                start = end

    return chunks
