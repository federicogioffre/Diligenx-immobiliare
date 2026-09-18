"""One readiness rule for API admission, document metadata and ingestion jobs."""
from typing import Literal


ProcessingIssue = Literal["pending", "processing", "failed", "missing_text"]


def document_processing_issue(status: str, raw_text: str | None) -> ProcessingIssue | None:
    if status == "processed":
        return None if raw_text and raw_text.strip() else "missing_text"
    if status == "pending":
        return "pending"
    if status == "processing":
        return "processing"
    return "failed"
