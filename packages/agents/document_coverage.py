"""Bounded, overlapping analysis of the complete extracted document.

Spans are zero-based character offsets into Document.raw_text, not inferred
PDF page numbers. A failing batch aborts collection before any persistence.
"""
from __future__ import annotations

import json
import logging
import re
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextBatch:
    start: int
    end: int
    text: str


def text_batches(text: str, max_chars: int = 8000, overlap: int = 600) -> Iterator[TextBatch]:
    for start, end in _text_batch_spans(text, max_chars=max_chars, overlap=overlap):
        yield TextBatch(start, end, text[start:end])


def _text_batch_spans(text: str, max_chars: int = 8000, overlap: int = 600) -> Iterator[tuple[int, int]]:
    """Count/iterate coverage without allocating copies of the document text."""
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
        yield start, end
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
        _merge_payloads(findings, analyze(batch.text), batch.start, batch.end)
    return list(findings.values())


def _merge_payloads(findings: dict[str, dict], items: list[dict], start: int, end: int) -> None:
    """Merge in source order, identically for sequential and parallel callers."""
    for item in items:
        identity = {k: v for k, v in item.items() if k not in {"confidence", "source_spans"}}
        key = json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str)
        span = {"start": start, "end": end}
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


@dataclass
class _DocumentCollection:
    document_id: int
    batches: Iterator[TextBatch]
    findings: dict[str, dict] = field(default_factory=dict)
    ready: dict[int, tuple[int, int, list[dict]]] = field(default_factory=dict)
    submitted: int = 0
    completed: int = 0
    next_merge: int = 0
    exhausted: bool = False
    logged_complete: bool = False


def collect_documents_payloads(
    documents: Sequence[tuple[int, str]],
    analyze: Callable[[int, str], list[dict]],
    *,
    max_chars: int = 8000,
    max_workers: int = 2,
    progress_context: str = "document_coverage",
    on_progress: Callable[[int, int, int], None] | None = None,
) -> list[list[dict]]:
    """Use one bounded batch queue across documents, including a single giant.

    At most max_workers futures are submitted, with text slices produced only
    when a slot is free. Round-robin scheduling lets small documents progress
    alongside a large one. Completed payloads contain offsets, never retained
    batch text, and merge in source order even when calls finish out of order.
    Workers receive plain values and must not use a database session. A failure
    prevents returning any collection; persistence remains the caller's job.
    """
    if max_workers < 1:
        raise ValueError("Batch concurrency must be positive")
    states = [_DocumentCollection(doc_id, text_batches(text, max_chars=max_chars))
              for doc_id, text in documents]
    total_batches = sum(1 for _, text in documents for _ in _text_batch_spans(text, max_chars=max_chars))
    completed_batches = 0
    logger.info("[%s] batch_queue documents=%d batches=%d concurrency=%d",
                progress_context, len(states), total_batches, max_workers)

    def log_complete(state: _DocumentCollection) -> None:
        if state.exhausted and state.completed == state.submitted and not state.logged_complete:
            state.logged_complete = True
            logger.info("[%s] document_complete doc=%d batches=%d",
                        progress_context, state.document_id, state.completed)

    def tasks():
        sources = deque(range(len(states)))
        while sources:
            doc_index = sources.popleft()
            state = states[doc_index]
            try:
                batch = next(state.batches)
            except StopIteration:
                state.exhausted = True
                log_complete(state)
                continue
            batch_index = state.submitted
            state.submitted += 1
            sources.append(doc_index)
            yield doc_index, batch_index, batch

    source = iter(tasks())
    pending: dict[Future, tuple[int, int, int, int]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        try:
            while True:
                while len(pending) < max_workers:
                    try:
                        doc_index, batch_index, batch = next(source)
                    except StopIteration:
                        break
                    future = executor.submit(analyze, states[doc_index].document_id, batch.text)
                    pending[future] = (doc_index, batch_index, batch.start, batch.end)
                if not pending:
                    break
                finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in finished:
                    doc_index, batch_index, start, end = pending.pop(future)
                    state = states[doc_index]
                    try:
                        items = future.result()
                    except Exception:
                        logger.error("[%s] batch_failed doc=%d batch=%d",
                                     progress_context, state.document_id, batch_index + 1)
                        raise
                    state.ready[batch_index] = (start, end, items)
                    state.completed += 1
                    while state.next_merge in state.ready:
                        ready_start, ready_end, ready_items = state.ready.pop(state.next_merge)
                        _merge_payloads(state.findings, ready_items, ready_start, ready_end)
                        state.next_merge += 1
                    logger.info("[%s] batch_complete doc=%d batch=%d completed_batches=%d",
                                progress_context, state.document_id, batch_index + 1, state.completed)
                    completed_batches += 1
                    if on_progress is not None:
                        try:
                            on_progress(completed_batches, total_batches, state.document_id)
                        except Exception:
                            # Telemetry is optional and must never invalidate evidence.
                            logger.warning("[%s] batch_progress_unavailable doc=%d",
                                           progress_context, state.document_id)
                    log_complete(state)
        except BaseException:
            for future in pending:
                future.cancel()
            raise
    return [list(state.findings.values()) for state in states]


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
