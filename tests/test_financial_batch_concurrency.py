"""A large financial document shares one bounded queue with all other documents."""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.config import settings
from app.models.agent_finding import AgentFinding
from app.models.document import Document, DocumentStatus
from packages.agents import document_coverage
from packages.agents.deal_analysis_agent import FakeLLMProvider, LLMResponseError
from packages.agents.document_coverage import (
    collect_document_payloads, collect_documents_payloads, text_batches,
)
from packages.agents.financial_agent import FinancialAgent


def _document(db, deal, text):
    doc = Document(deal_id=deal.id, filename="private-ledger.txt", file_path="/unused",
                   mime_type="text/plain", file_size=len(text), status=DocumentStatus.processed,
                   raw_text=text)
    db.add(doc)
    db.commit()
    return doc


def test_single_huge_financial_document_uses_two_workers_and_all_original_spans(db, test_deal, monkeypatch, caplog):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENCY", 4)
    monkeypatch.setattr(settings, "LLM_MAX_IN_FLIGHT", 4)
    text = "".join(f"Row {index:06d}: synthetic ledger evidence for this regression.\n"
                   for index in range(16000)) + "PRIVATE_TAIL_MARKER"
    doc = _document(db, test_deal, text)
    document_id = doc.id
    expected = [batch.text for batch in text_batches(text)]
    assert len(expected) > 100
    lock, first_pair = threading.Lock(), threading.Barrier(2)
    active = peak = calls = 0
    seen = []

    def analyze(filename, batch, doc_id):
        nonlocal active, peak, calls
        assert doc_id == document_id
        with lock:
            active += 1
            peak = max(peak, active)
            calls += 1
            call = calls
            seen.append(batch)
        try:
            if call <= 2:
                first_pair.wait(timeout=3)
            time.sleep(0.001)
            return []
        finally:
            with lock:
                active -= 1

    agent = FinancialAgent(provider=FakeLLMProvider())
    monkeypatch.setattr(agent, "_financial_payloads_batch", analyze)
    with caplog.at_level(logging.INFO, logger="packages.agents.document_coverage"):
        result = agent.run(test_deal.id, db, document_ids={document_id})
    assert result["documents_analyzed"] == 1
    assert calls == len(expected)
    assert sorted(seen) == sorted(expected)
    assert peak == 2
    progress = [record.getMessage() for record in caplog.records
                if record.name == "packages.agents.document_coverage"]
    assert sum("batch_complete" in message for message in progress) == len(expected)
    assert any(f"document_complete doc={document_id} batches={len(expected)}" in message for message in progress)
    assert not any("PRIVATE_TAIL_MARKER" in message or "private-ledger.txt" in message for message in progress)


@pytest.mark.parametrize("limited_setting", ["LLM_MAX_CONCURRENCY", "LLM_MAX_IN_FLIGHT"])
def test_financial_stage_respects_a_lower_configured_ceiling(db, test_deal, monkeypatch, limited_setting):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENCY", 4)
    monkeypatch.setattr(settings, "LLM_MAX_IN_FLIGHT", 4)
    monkeypatch.setattr(settings, limited_setting, 1)
    docs = [_document(db, test_deal, str(index) + "x" * 24000) for index in range(3)]
    lock = threading.Lock()
    active = peak = 0

    def analyze(*args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.002)
        with lock:
            active -= 1
        return []

    agent = FinancialAgent(provider=FakeLLMProvider())
    monkeypatch.setattr(agent, "_financial_payloads_batch", analyze)
    result = agent.run(test_deal.id, db, document_ids={doc.id for doc in docs})
    assert result["documents_analyzed"] == 3
    assert peak == 1


def test_submission_is_lazy_and_concurrency_is_global_across_documents(monkeypatch):
    started, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    generated = active = peak = 0
    original = document_coverage.text_batches

    def counted(text, **kwargs):
        nonlocal generated
        for batch in original(text, **kwargs):
            with lock:
                generated += 1
            yield batch

    def analyze(document_id, batch):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                started.set()
        try:
            assert release.wait(3), "test did not release the batch workers"
            return []
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(document_coverage, "text_batches", counted)
    with ThreadPoolExecutor(max_workers=1) as caller:
        job = caller.submit(collect_documents_payloads,
                            [(i, "x" * 160000) for i in range(18)], analyze, max_workers=2)
        try:
            assert started.wait(3)
            assert generated == 2  # No eager slicing/submission of the remaining corpus.
            assert peak == 2
        finally:
            release.set()
        assert job.result(timeout=5) == [[] for _ in range(18)]
    assert peak == 2


def test_out_of_order_results_preserve_sequential_order_dedup_confidence_and_offsets():
    texts = ["".join(f"Doc {doc_id} row {i:05d}\n" for i in range(2000)) for doc_id in (7, 9)]
    documents = list(zip((7, 9), texts))
    indices = {doc_id: {batch.text: index for index, batch in enumerate(text_batches(text))}
               for doc_id, text in documents}

    def payloads(doc_id, batch):
        index = indices[doc_id][batch]
        return [{"title": "Repeated debt", "amount": doc_id, "confidence": index / 10},
                {"title": "Different amount", "amount": index + 100, "confidence": 0.9}]

    expected = [collect_document_payloads(text, lambda batch, doc_id=doc_id: payloads(doc_id, batch))
                for doc_id, text in documents]
    later_finished = threading.Event()

    def delayed(doc_id, batch):
        index = indices[doc_id][batch]
        if doc_id == 7 and index == 0:
            assert later_finished.wait(3)
        else:
            later_finished.set()
        return payloads(doc_id, batch)

    result = collect_documents_payloads(documents, delayed, max_workers=2)
    assert result == expected
    for items, text in zip(result, texts):
        assert items[0]["source_spans"] == [{"start": batch.start, "end": batch.end}
                                            for batch in text_batches(text)]
        assert items[0]["confidence"] == (len(list(text_batches(text))) - 1) / 10


def test_one_failed_batch_aborts_stage_without_replacing_previous_findings(db, test_deal, monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENCY", 4)
    monkeypatch.setattr(settings, "LLM_MAX_IN_FLIGHT", 4)
    text = "".join(f"Evidence row {i:06d}\n" for i in range(4000))
    doc = _document(db, test_deal, text)
    original = AgentFinding(deal_id=test_deal.id, document_id=doc.id, agent_name="financial_analysis",
                            category="equity_position", title="Previous result", description="Keep me",
                            severity="low", confidence=0.9)
    db.add(original)
    db.commit()
    failed_text = list(text_batches(text))[2].text

    def analyze(filename, batch, doc_id):
        if batch == failed_text:
            raise LLMResponseError("Synthetic batch failure")
        return [{"finding_type": "equity_position", "title": "New finding", "description": "New",
                 "severity": "low", "confidence": 0.9, "source": "llm"}]

    agent = FinancialAgent(provider=FakeLLMProvider())
    monkeypatch.setattr(agent, "_financial_payloads_batch", analyze)
    with pytest.raises(LLMResponseError, match="Synthetic batch failure"):
        agent.run(test_deal.id, db, document_ids={doc.id})
    db.rollback()
    remaining = db.query(AgentFinding).filter_by(agent_name="financial_analysis").all()
    assert len(remaining) == 1
    assert remaining[0].title == "Previous result"


def test_empty_documents_keep_input_positions_without_calls():
    def never(*args):
        raise AssertionError("empty documents must not call the provider")

    assert collect_documents_payloads([], never) == []
    assert collect_documents_payloads([(10, ""), (20, "")], never) == [[], []]


def test_progress_has_exact_total_runs_on_caller_and_cannot_fail_analysis():
    caller_thread = threading.get_ident()
    documents = [(10, "x" * 17000), (20, "y" * 10000)]
    expected_total = sum(len(list(text_batches(text))) for _, text in documents)
    progress = []

    def publish(done, total, document_id):
        assert threading.get_ident() == caller_thread
        progress.append((done, total, document_id))
        if done == 2:
            raise ConnectionError("progress service unavailable")

    assert collect_documents_payloads(documents, lambda *_: [], on_progress=publish) == [[], []]
    assert [done for done, _, _ in progress] == list(range(1, expected_total + 1))
    assert {total for _, total, _ in progress} == {expected_total}
    assert {document_id for _, _, document_id in progress} == {10, 20}
