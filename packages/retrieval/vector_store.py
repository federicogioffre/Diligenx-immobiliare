"""Vector store abstraction. Swap backend (ChromaDB, Pinecone, pgvector) as needed."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Document:
    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore:
    """Simple in-memory vector store placeholder."""

    def __init__(self):
        self._docs: list[Document] = []

    def add(self, doc: Document) -> None:
        self._docs.append(doc)

    def search(self, query: str, top_k: int = 5) -> list[Document]:
        # Placeholder: replace with actual embedding + similarity search
        return self._docs[:top_k]

    def clear(self) -> None:
        self._docs.clear()
