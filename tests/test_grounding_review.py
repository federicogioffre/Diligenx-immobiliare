"""Replay the observed defective drafts through the production review boundary.

Provider responses are scripted: these are regression tests for the full source
context, replacement/validation/persistence contract, not an LLM quality eval.
"""
import copy
import json
from pathlib import Path

import pytest

from packages.agents.deal_analysis_agent import FakeLLMProvider, LLMResponseError
from packages.agents.grounding_review import review_grounded_flags, review_grounded_text


@pytest.fixture
def replay():
    return json.loads((Path(__file__).parent / "fixtures/grounding_replay_2026_09_19.json").read_text("utf-8"))


class ReplayReviewer:
    """Independent reviewer fixture that sees all limiting source clauses."""
    def __init__(self, flags=None):
        self.flags = flags
        self.prompts = []

    def complete(self, prompt, max_tokens=2048):
        if "GROUNDING REVIEW\n" not in prompt:
            return json.dumps(self.flags)
        self.prompts.append(prompt)
        payload = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        document = payload["documents"][0]
        draft = payload["items"][0]["candidate"]
        doc_id = document["document_id"]
        source = document["text"]
        if "DSCR" in draft["title"]:
            # Both distinct triggers, the notice/cure period and non-exercise
            # must reach the reviewer, even though the draft omitted them.
            assert "30 giorni dalla contestazione scritta" in source
            assert "non\ndetermina automaticamente" in source
            assert "1,20" in source and "0,85" in source
            fields = {
                "title": "Violazione del covenant DSCR e consenso al cambio di controllo",
                "issue": "Il DSCR risulta 0,85 rispetto al minimo 1,20. La cessione richiede il consenso scritto della banca.",
                "risk": "Per il covenant DSCR il rimborso può essere richiesto dopo 30 giorni dalla contestazione scritta; non è documentato l'esercizio del diritto. Per il cambio di controllo senza consenso la banca può dichiarare il capitale immediatamente esigibile.",
                "recommendation": "Ottenere il consenso della banca e concordare una soluzione per la violazione del covenant prima del perfezionamento.",
            }
            quotes = [
                "Il rapporto DSCR deve essere almeno 1,20 a ogni verifica annuale. Il certificato finanziario allegato per il 2025 riporta DSCR pari a 0,85. Non e stata fornita alcuna deroga scritta della banca.",
                "In caso di violazione del covenant DSCR, la banca puo richiedere il rimborso anticipato dopo un termine di rimedio di 30 giorni dalla contestazione scritta. La violazione del covenant non determina automaticamente l'avvenuto esercizio di questo diritto.",
                "La cessione di oltre il 50% delle quote di Aurora Collaudo S.r.l. richiede il previo consenso scritto della banca. In mancanza di tale consenso, la banca puo dichiarare immediatamente esigibile l'intero capitale residuo di EUR 250.000,00.",
                "Non e documentata una richiesta di rimborso anticipato gia inviata dalla banca.",
            ]
        else:
            assert "non e indicato un fondo svalutazione" in source
            fields = {
                "title": "Crediti scaduti: fondo svalutazione non documentato",
                "issue": draft["issue"],
                "risk": draft["risk"],
                "recommendation": "Verificare la recuperabilità dei crediti e l'eventuale fondo prima di concordare un aggiustamento del prezzo.",
            }
            quotes = ["Su crediti commerciali complessivi di EUR 300.000,00, EUR 120.000,00 risultano scaduti da oltre 180 giorni. Non e fornita una valutazione di recuperabilita e non e indicato un fondo svalutazione per tali crediti."]
        return json.dumps([{"index": 0, "supported": True, "fields": fields,
                            "evidence": [{"source_document_id": doc_id, "quote": quote,
                                          "fields": ["title", "issue", "risk"]} for quote in quotes]}])


def test_replay_repairs_qualifications_and_preserves_multiple_pages(replay):
    reviewer = ReplayReviewer()
    flags = review_grounded_flags(reviewer, replay["flags"], replay["documents"], "it")
    loan, receivables = flags
    assert "30 giorni dalla contestazione scritta" in loan["risk"]
    assert "non è documentato" in loan["risk"]
    assert "art. p.2" not in loan["issue"]
    assert loan["source_page"] is None
    assert loan["source_pages"] == [
        {"source_document_id": 241, "page": 1}, {"source_document_id": 241, "page": 2}]
    assert "non documentato" in receivables["title"]
    assert "senza fondo" not in receivables["title"]
    assert receivables["source_page"] == 1  # No contract clause needed to locate financial evidence.
    assert loan["amount_eur"] == 250000
    assert receivables["amount_eur"] == 120000
    assert len(reviewer.prompts) == 2


class MutatingReview:
    def __init__(self, mutate):
        self.mutate = mutate
        self.calls = 0

    def complete(self, prompt, max_tokens=2048):
        self.calls += 1
        result = json.loads(ReplayReviewer().complete(prompt, max_tokens))
        self.mutate(result)
        return json.dumps(result)


@pytest.mark.parametrize("mutate", [
    lambda result: result.clear(),
    lambda result: result.append(copy.deepcopy(result[0])),
    lambda result: result[0].update(index=True),
    lambda result: result[0].update(supported=False),
    lambda result: result[0]["fields"].pop("risk"),
    lambda result: result[0]["fields"].update(risk=None),
    lambda result: result[0]["fields"].update(title=""),
    lambda result: result[0]["fields"].update(title="Un titolo " * 100),
    lambda result: result[0]["fields"].update(issue="Il covenant è violato (art. p.2)."),
    lambda result: result[0]["fields"].update(recommendation="Insert a specific indemnity in the SPA for the benefit of the Buyer."),
    lambda result: result[0].update(evidence=[]),
    lambda result: result[0]["evidence"][0].update(quote="The bank has already demanded payment."),
    lambda result: result[0]["evidence"][0].update(source_document_id=999),
    lambda result: [entry.update(fields=["title"]) for entry in result[0]["evidence"]],
])
def test_invalid_semantic_review_fails_once_without_silent_fallback(replay, mutate):
    reviewer = MutatingReview(mutate)
    with pytest.raises(LLMResponseError):
        review_grounded_flags(reviewer, replay["flags"][:1], replay["documents"], "it")
    assert reviewer.calls == 1


def test_review_happens_before_deleting_previous_outputs(db, test_deal, replay):
    from app.models.document import Document, DocumentStatus
    from app.models.red_flag import RedFlag, Severity
    from packages.agents.red_flag_aggregator import RedFlagAggregationAgent
    document = Document(deal_id=test_deal.id, filename="loan.pdf", file_path="/tmp/loan.pdf",
                        mime_type="application/pdf", file_size=100, status=DocumentStatus.processed,
                        raw_text=replay["documents"][0]["text"])
    db.add(document)
    db.flush()
    previous = RedFlag(deal_id=test_deal.id, title="Previous reviewed result", issue="Preserve me",
                       category="liability", severity=Severity.high)
    db.add(previous)
    db.commit()
    draft = {**replay["flags"][0], "source_document_id": document.id}

    class BrokenReview(FakeLLMProvider):
        def complete(self, prompt, max_tokens=2048):
            if "GROUNDING REVIEW\n" in prompt:
                return "[]"
            return json.dumps([draft])

    with pytest.raises(LLMResponseError, match="every draft"):
        RedFlagAggregationAgent(BrokenReview()).run(test_deal.id, db)
    assert db.query(RedFlag).filter_by(deal_id=test_deal.id).one().title == "Previous reviewed result"


def test_persistence_records_verified_pages_and_corrected_prose(db, test_deal, replay):
    from app.models.document import Document, DocumentStatus
    from app.models.document_chunk import DocumentChunk
    from app.models.red_flag import RedFlag
    from packages.agents.red_flag_aggregator import RedFlagAggregationAgent
    test_deal.report_language = "it"
    docs = replay["documents"]
    flags = replay["flags"]
    for source, flag in zip(docs, flags):
        document = Document(deal_id=test_deal.id, filename=source["filename"], file_path="/tmp/fixture",
                            mime_type="application/pdf", file_size=100, status=DocumentStatus.processed,
                            raw_text=source["text"], page_count=source["page_count"])
        db.add(document)
        db.flush()
        flag["source_document_id"] = document.id
        for index, page in enumerate(source["pages"]):
            db.add(DocumentChunk(document_id=document.id, chunk_index=index, **page))
    db.commit()
    RedFlagAggregationAgent(ReplayReviewer(flags)).run(test_deal.id, db)
    persisted = db.query(RedFlag).order_by(RedFlag.id).all()
    assert len(persisted) == 2
    assert "30 giorni" in persisted[0].risk
    assert persisted[0].source_page is None
    assert [p["page"] for p in persisted[0].structured_payload_json["source_pages"]] == [1, 2]
    assert persisted[1].source_page == 1
    assert "non documentato" in persisted[1].title
    assert persisted[0].structured_payload_json["amount_eur"] == 250000


def test_summary_review_repairs_epistemic_drift_against_reviewed_findings():
    original = "I crediti sono privi di fondo svalutazione."
    source = "Non è indicato un fondo svalutazione per i crediti scaduti."

    class SummaryReviewer:
        def complete(self, prompt, max_tokens=2048):
            payload = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
            assert payload["kind"] == "text"
            assert payload["items"][0]["candidate"]["text"] == original
            assert payload["documents"][0]["text"] == source
            return json.dumps([{"index": 0, "supported": True,
                                "fields": {"text": "Il fondo svalutazione dei crediti scaduti non è documentato."},
                                "evidence": [{"source_document_id": 5, "quote": source, "fields": ["text"]}]}])

    fixed = review_grounded_text(SummaryReviewer(), original, [{"document_id": 5, "text": source}], "it")
    assert "non è documentato" in fixed


def test_long_document_review_includes_distant_limiting_clauses(replay):
    loan = replay["documents"][0]
    # The real qualification survives in a distant appendix, well past prefixes.
    loan["text"] = loan["pages"][0]["content"] + ("Unrelated boilerplate.\n" * 8000) + loan["pages"][1]["content"]
    reviewer = ReplayReviewer()
    fixed = review_grounded_flags(reviewer, replay["flags"][:1], [loan], "it")
    assert "30 giorni" in fixed[0]["risk"]
    assert len(reviewer.prompts) == 1
    assert len(reviewer.prompts[0]) < 20000


def test_large_source_without_anchors_is_fully_covered_in_bounded_windows():
    text = "First paragraph.\n" + ("Boilerplate.\n" * 18000) + "LAST SOURCE LIMITATION."
    seen = []

    class WindowReviewer:
        def complete(self, prompt, max_tokens=2048):
            payload = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
            source = payload["documents"][0]["text"]
            seen.append(source)
            return json.dumps([{"index": 0, "supported": True, "fields": {
                "title": "Review", "issue": "A source issue.", "risk": None, "recommendation": None},
                "evidence": [{"source_document_id": 1, "quote": source[:20], "fields": ["title", "issue"]}]}])

    flags = review_grounded_flags(WindowReviewer(), [{"title": "Review", "issue": "A source issue.", "source_document_id": 1}],
                                  [{"document_id": 1, "text": text}], "en")
    assert len(seen) > 1
    assert "First paragraph." in seen[0]
    assert "LAST SOURCE LIMITATION." in seen[-1]
    assert all(len(window) <= 40000 for window in seen)
    assert flags[0]["grounding_reviewed"] is True


@pytest.mark.parametrize("documents", [[], [{"document_id": 1, "text": ""}]])
def test_no_evidence_never_bypasses_review(documents):
    with pytest.raises(LLMResponseError, match="without source evidence"):
        review_grounded_flags(FakeLLMProvider(), [{"title": "Unsupported claim"}], documents, "en")


def test_nonempty_summary_without_evidence_fails_closed():
    with pytest.raises(LLMResponseError, match="without source evidence"):
        review_grounded_text(FakeLLMProvider(), "The transaction presents no risk.", [], "en")


def test_secondary_sources_are_visible_to_the_reviewer():
    class CrossFileReviewer:
        def complete(self, prompt, max_tokens=2048):
            payload = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
            assert {source["document_id"] for source in payload["documents"]} == {1, 2}
            return json.dumps([{"index": 0, "supported": True, "fields": {
                "title": "Notice disputed", "issue": "Notice was issued but then withdrawn.",
                "risk": None, "recommendation": None}, "evidence": [
                    {"source_document_id": 1, "quote": "Notice issued.", "fields": ["title", "issue"]},
                    {"source_document_id": 2, "quote": "Notice withdrawn.", "fields": ["title", "issue"]}]}])

    result = review_grounded_flags(CrossFileReviewer(), [{"title": "Notice due", "issue": "Notice issued.",
                                   "source_document_id": 1, "evidence": [{"source_document_id": 2, "quote": "Notice withdrawn."}]}],
                                  [{"document_id": 1, "text": "Notice issued."}, {"document_id": 2, "text": "Notice withdrawn."}], "en")
    assert "withdrawn" in result[0]["issue"]
    assert {entry["source_document_id"] for entry in result[0]["evidence"]} == {1, 2}


def test_discontinuous_source_windows_cannot_manufacture_a_verbatim_quote():
    class WindowQuote:
        def complete(self, prompt, max_tokens=2048):
            payload = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
            source = payload["documents"][0]["text"]
            assert "[... source interval ...]" in source
            return json.dumps([{"index": 0, "supported": True, "fields": {
                "title": "Notice", "issue": "Notice issued.", "risk": None, "recommendation": None},
                "evidence": [{"source_document_id": 1, "quote": source, "fields": ["title", "issue"]}]}])

    with pytest.raises(LLMResponseError, match="unsupported evidence"):
        review_grounded_flags(WindowQuote(), [{"title": "Notice", "source_document_id": 1}],
                              [{"document_id": 1, "text": "FIRST ANCHOR." + "x" * 50000 + "LAST ANCHOR.",
                                "anchors": ["FIRST ANCHOR.", "LAST ANCHOR."]}], "en")


def test_a_later_rewrite_cannot_reuse_earlier_field_evidence():
    class RewritingWindow:
        count = 0
        def complete(self, prompt, max_tokens=2048):
            self.count += 1
            risk = "Repayment follows a 30 day cure period." if self.count == 1 else "Repayment is immediately due."
            return json.dumps([{"index": 0, "supported": True, "fields": {
                "title": "Default", "issue": "Breach identified.", "risk": risk, "recommendation": None},
                "evidence": ([{"source_document_id": 1, "quote": "30 day cure period.",
                               "fields": ["title", "issue", "risk"]}] if self.count == 1 else [])}])

    with pytest.raises(LLMResponseError, match="without evidence"):
        review_grounded_flags(RewritingWindow(), [{"title": "Default", "source_document_id": 1}],
                              [{"document_id": 1, "text": "30 day cure period.\n" + "Boilerplate.\n" * 18000}], "en")
