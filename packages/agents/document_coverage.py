"""Bounded, overlapping analysis of the complete extracted document.

Spans are zero-based character offsets into Document.raw_text, not inferred
PDF page numbers. A failing batch aborts collection before any persistence.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class TextBatch:
    start: int
    end: int
    text: str


def text_batches(text: str, max_chars: int = 8000, overlap: int = 600) -> Iterator[TextBatch]:
    if not 0 <= overlap < max_chars:
        raise ValueError("Batch overlap must be smaller than the batch size")
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Prefer an existing paragraph boundary without dropping any text.
            boundary = text.rfind("\n", start + max_chars // 2, end)
            if boundary >= 0:
                end = boundary + 1
        yield TextBatch(start, end, text[start:end])
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def collect_document_payloads(
    text: str,
    analyze: Callable[[str], list[dict]],
    *,
    max_chars: int = 8000,
) -> list[dict]:
    """Analyze all spans; merge only identical findings from overlapping spans."""
    findings: dict[str, dict] = {}
    for batch in text_batches(text, max_chars=max_chars):
        for item in analyze(batch.text):
            identity = {k: v for k, v in item.items() if k not in {"confidence", "source_spans"}}
            key = json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str)
            span = {"start": batch.start, "end": batch.end}
            if key not in findings:
                findings[key] = {**item, "source_spans": [span]}
            else:
                if span not in findings[key]["source_spans"]:
                    findings[key]["source_spans"].append(span)
                confidence = item.get("confidence")
                old_confidence = findings[key].get("confidence")
                if isinstance(confidence, (int, float)) and (
                    old_confidence is None or confidence > old_confidence
                ):
                    findings[key]["confidence"] = confidence
    return list(findings.values())


def aggregation_batches(context: str, max_chars: int = 8000) -> list[str]:
    """Bound aggregation inputs and repeat document identity on continuations.

    The original specialist records remain the source of truth; consolidation
    results are combined deterministically, never passed through an unbounded
    final LLM prompt.
    """
    if len(context) <= max_chars:
        return [context]
    batches: list[str] = []
    current = ""
    for block in re.split(r"(?m)(?=^=== )", context):
        if not block:
            continue
        header, separator, body = block.partition("\n")
        if not header.startswith("=== "):
            header, body = "", block
        prefix = header + "\n" if header else ""
        capacity = max_chars - len(prefix)
        if capacity < 100:
            raise ValueError("Document context header exceeds aggregation budget")
        for part in text_batches(body or "\n", max_chars=capacity, overlap=0):
            piece = prefix + part.text
            if current and len(current) + len(piece) + 1 > max_chars:
                batches.append(current)
                current = ""
            current = current + "\n" + piece if current else piece
    if current:
        batches.append(current)
    return batches
