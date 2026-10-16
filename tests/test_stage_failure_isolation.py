"""One document whose model request fails must not discard the stage.

The production run of 2026-09-20 lost 80 correctly analysed contracts because
one two-page leasing contract sent the model into a runaway generation
(2k tokens in, 12k tokens out, truncated). These tests pin the replacement
semantics: the failing document is recorded as an open question, the other
documents' results are persisted, and only a stage where every document fails
still fails.
"""
import json

import pytest

from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.agent_finding import AgentFinding
from app.models.document import Document, DocumentStatus
from app.models.open_question import OpenQuestion, Priority
from packages.agents.concurrency import TaskFailure, run_llm_tasks
from packages.agents.deal_analysis_agent import (
    FakeLLMProvider, LLMResponseError, LLMTruncatedError, _complete_json, set_llm_provider,
)
from packages.agents.document_coverage import collect_documents_payloads, text_batches
from packages.real_estate.fake_provider import FakeRealEstateLLMProvider
from packages.real_estate.specialists import EncumbrancesAgent

AGENT_NAME = EncumbrancesAgent.AGENT_NAME


@pytest.fixture(autouse=True)
def use_fake_llm():
    set_llm_provider(FakeLLMProvider())
    yield
    set_llm_provider(None)


def _document(db, deal, filename, text):
    doc = Document(deal_id=deal.id, filename=filename, file_path=f"/tmp/{filename}",
                   mime_type="application/pdf", file_size=100, status=DocumentStatus.processed,
                   raw_text=text)
    db.add(doc)
    db.flush()
    return doc


# ── run_llm_tasks ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("workers", [1, 3])
def test_isolated_failure_keeps_the_other_results_in_order(workers):
    def worker(x):
        if x == 2:
            raise LLMResponseError("boom")
        return x * 10

    results = run_llm_tasks([1, 2, 3], worker, max_workers=workers, isolate_failures=True)
    assert results[0] == 10 and results[2] == 30
    assert isinstance(results[1], TaskFailure)
    assert results[1].error == "boom"
    assert isinstance(results[1].exception, LLMResponseError)


def test_every_item_failing_still_raises():
    def worker(x):
        raise RuntimeError("credentials")

    with pytest.raises(RuntimeError, match="credentials"):
        run_llm_tasks([1, 2], worker, max_workers=2, isolate_failures=True)


def test_default_mode_still_propagates():
    def worker(x):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        run_llm_tasks([1, 2], worker, max_workers=2)


# ── collect_documents_payloads ─────────────────────────────────────────────

def test_a_failed_batch_fails_only_its_document():
    long_text = "".join(f"Row {i:05d}\n" for i in range(3000))
    short_text = "A short document with one finding."
    failing = list(text_batches(long_text))[1].text
    calls = []

    def analyze(document_id, batch):
        calls.append(document_id)
        if batch == failing:
            raise LLMResponseError("truncated")
        return [{"title": f"finding of {document_id}", "severity": "low"}]

    results = collect_documents_payloads([(1, long_text), (2, short_text)], analyze,
                                         max_workers=2, isolate_failures=True)
    assert isinstance(results[0], TaskFailure)
    assert "truncated" in results[0].error
    assert [item["title"] for item in results[1]] == ["finding of 2"]
    # The failed document's remaining batches are not requested.
    assert calls.count(1) < len(list(text_batches(long_text)))


def test_all_documents_failing_in_the_batch_queue_raises():
    def analyze(document_id, batch):
        raise LLMResponseError("down")

    with pytest.raises(LLMResponseError, match="down"):
        collect_documents_payloads([(1, "one"), (2, "two")], analyze, max_workers=2, isolate_failures=True)


# ── truncation retry ───────────────────────────────────────────────────────

def test_a_truncated_answer_is_retried_once_with_a_compactness_instruction():
    prompts = []

    class RunawayOnce:
        def complete(self, prompt, max_tokens=2048):
            prompts.append(prompt)
            if len(prompts) == 1:
                raise LLMTruncatedError("AI response was truncated at the output token limit")
            return json.dumps([{"ok": True}])

    result = _complete_json(RunawayOnce(), "TASK", max_tokens=100, context="ctx", response_type="array")
    assert result == [{"ok": True}]
    assert len(prompts) == 2
    assert prompts[1].startswith("OUTPUT LIMIT RETRY:") and prompts[1].endswith("TASK")


def test_a_second_truncation_is_final():
    class Runaway:
        def complete(self, prompt, max_tokens=2048):
            raise LLMTruncatedError("AI response was truncated at the output token limit")

    with pytest.raises(LLMResponseError, match="ctx: .*truncated.*after 2 attempts"):
        _complete_json(Runaway(), "TASK", max_tokens=100, context="ctx", response_type="array")


# ── review stage end to end ────────────────────────────────────────────────

class RunawayOnOneSearch(FakeRealEstateLLMProvider):
    """Loops forever on one registry search, answers normally elsewhere."""

    def complete(self, prompt, max_tokens=2048):
        if "REVIEW ENCUMBRANCES" in prompt.upper() and "ISPEZIONE ROSSI" in prompt:
            raise LLMTruncatedError("AI response was truncated at the output token limit")
        return super().complete(prompt, max_tokens)


GOOD = "ISPEZIONE IPOTECARIA BIANCHI\nIpoteca volontaria iscritta in data 01/06/2015 a favore di Banca.\n"
BAD = "ISPEZIONE ROSSI\nIspezione ipotecaria. Ipoteca volontaria iscritta in data 02/02/2012.\n"


def test_review_stage_keeps_the_other_documents_and_records_the_failed_one(db, test_deal):
    test_deal.report_language = "it"
    good = _document(db, test_deal, "ispezione_bianchi.pdf", GOOD)
    bad = _document(db, test_deal, "ISPEZIONE ROSSI.pdf", BAD)
    db.commit()

    result = EncumbrancesAgent(provider=RunawayOnOneSearch()).run(test_deal.id, db)

    assert db.query(AgentFinding).filter_by(document_id=good.id, agent_name=AGENT_NAME).count() >= 1
    assert db.query(AgentFinding).filter_by(document_id=bad.id, agent_name=AGENT_NAME).count() == 0
    assert result["failed_documents"] == [{
        "document_id": bad.id, "filename": bad.filename,
        "error": "%s, document %d: AI response was truncated at the output token limit (after 2 attempts)"
                 % (AGENT_NAME, bad.id),
    }]
    question = db.query(OpenQuestion).filter_by(deal_id=test_deal.id, agent_name=AGENT_NAME).one()
    assert question.priority == Priority.medium
    assert question.document_id == bad.id
    assert question.question.startswith("Documento non analizzato")
    assert "ISPEZIONE ROSSI.pdf" in question.question

    run = db.query(AgentRun).filter_by(deal_id=test_deal.id, agent_name=AGENT_NAME).one()
    assert run.status == AgentRunStatus.completed


def test_a_document_that_analyses_on_the_next_run_clears_its_question(db, test_deal):
    _document(db, test_deal, "ISPEZIONE ROSSI.pdf", BAD)
    _document(db, test_deal, "ispezione_bianchi.pdf", GOOD)
    db.commit()
    EncumbrancesAgent(provider=RunawayOnOneSearch()).run(test_deal.id, db)
    assert db.query(OpenQuestion).filter_by(agent_name=AGENT_NAME).count() == 1
    EncumbrancesAgent(provider=FakeRealEstateLLMProvider()).run(test_deal.id, db)
    assert db.query(OpenQuestion).filter_by(agent_name=AGENT_NAME).count() == 0


def test_every_document_failing_still_fails_the_review_stage(db, test_deal):
    _document(db, test_deal, "ISPEZIONE ROSSI.pdf", BAD)
    db.commit()
    with pytest.raises(LLMResponseError, match="truncated"):
        EncumbrancesAgent(provider=RunawayOnOneSearch()).run(test_deal.id, db)
