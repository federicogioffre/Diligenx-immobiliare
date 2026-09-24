"""Replay the observed defective drafts through the production review boundary.

Provider responses are scripted: these are regression tests for the full source
context, replacement/validation/persistence contract, not an LLM quality eval.
"""
import copy
import json
from pathlib import Path

import pytest

from packages.agents.deal_analysis_agent import FakeLLMProvider, LLMResponseError, PromptSegment, prompt_text
from packages.agents.grounding_review import (
    review_grounded_flags, review_grounded_text, review_payload,
)


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
        payload = review_payload(prompt)
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


@pytest.mark.parametrize(("mutate", "attempts"), [
    (lambda result: result.clear(), 2),
    (lambda result: result.append(copy.deepcopy(result[0])), 2),
    (lambda result: result[0].update(index=True), 2),
    (lambda result: result[0].update(supported=False), 2),
    (lambda result: result[0]["fields"].pop("risk"), 2),
    (lambda result: result[0]["fields"].update(risk=None), 1),
    (lambda result: result[0]["fields"].update(title=""), 1),
    (lambda result: result[0]["fields"].update(title="Un titolo " * 100), 1),
    (lambda result: result[0]["fields"].update(issue="Il covenant è violato (art. p.2)."), 1),
    (lambda result: result[0]["fields"].update(recommendation="Insert a specific indemnity in the SPA for the benefit of the Buyer."), 1),
    (lambda result: result[0].update(evidence=[]), 2),
    (lambda result: result[0]["evidence"][0].update(quote="The bank has already demanded payment."), 2),
    (lambda result: result[0]["evidence"][0].update(source_document_id=999), 2),
    (lambda result: [entry.update(fields=["title"]) for entry in result[0]["evidence"]], 2),
])
def test_invalid_review_never_publishes_and_correction_is_bounded(replay, mutate, attempts):
    reviewer = MutatingReview(mutate)
    with pytest.raises(LLMResponseError):
        review_grounded_flags(reviewer, replay["flags"][:1], replay["documents"], "it")
    assert reviewer.calls == attempts


def test_incomplete_narrative_fields_retry_with_complete_original_evidence(replay):
    class OnceIncomplete(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            if len(self.prompts) == 1:
                response[0]["fields"].pop("risk")
            return json.dumps(response)

    reviewer = OnceIncomplete()
    result = review_grounded_flags(reviewer, replay["flags"][:1], replay["documents"], "it")
    assert len(reviewer.prompts) == 2
    assert reviewer.prompts[1].endswith(reviewer.prompts[0])
    assert result[0]["risk"]
    assert result[0]["grounding_reviewed"] is True


@pytest.mark.parametrize("wrong_document", [False, True])
def test_citation_correction_receives_feedback_and_must_pass_verbatim_checks(replay, wrong_document):
    class OnceInvalidCitation(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            if len(self.prompts) == 1:
                response[0]["evidence"][0].update(
                    {"source_document_id": 999} if wrong_document else {"quote": "DSCR ... 0,85"}
                )
            else:
                data = review_payload(prompt)
                defect = data["validation_feedback"]["defects"][0]
                assert defect["draft_index"] == 0
                assert defect["reason"]
                assert data["documents"][0]["text"] == replay["documents"][0]["text"]
            return json.dumps(response)

    reviewer = OnceInvalidCitation()
    result = review_grounded_flags(reviewer, replay["flags"][:1], replay["documents"], "it")
    assert len(reviewer.prompts) == 2
    assert result[0]["grounding_reviewed"] is True
    for entry in result[0]["evidence"]:
        source = next(d for d in replay["documents"] if d["document_id"] == entry["source_document_id"])
        assert " ".join(entry["quote"].split()).casefold() in " ".join(source["text"].split()).casefold()


def test_citation_correction_cannot_override_a_negative_support_decision(replay):
    class CannotRepair(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            if len(self.prompts) == 1:
                response[0]["evidence"][0]["quote"] = "Invented quotation"
            else:
                response[0]["supported"] = False
            return json.dumps(response)

    reviewer = CannotRepair()
    with pytest.raises(LLMResponseError, match="could not support"):
        review_grounded_flags(reviewer, replay["flags"][:1], replay["documents"], "it")
    assert len(reviewer.prompts) == 2


def test_bad_citation_and_unsupported_draft_share_one_correction_budget(replay):
    class MixedDecisions(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            rejected = copy.deepcopy(response[0])
            rejected.update(index=1, supported=False)
            response[0]["evidence"][0]["quote"] = "Invented quotation"
            return json.dumps([response[0], rejected])

    reviewer = MixedDecisions()
    with pytest.raises(LLMResponseError, match="could not support"):
        review_grounded_flags(reviewer, [replay["flags"][0]] * 2, replay["documents"], "it")
    assert len(reviewer.prompts) == 2


def test_unsupported_draft_gets_one_informed_repair_without_losing_source_conditions(replay):
    class RepairableDraft(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            data = review_payload(prompt)
            if len(self.prompts) == 1:
                response[0].update(supported=False, support_reason="Il rimborso non è automaticamente dovuto.",
                                   evidence=[])
                response[0]["fields"]["risk"] = "Il rimborso è automaticamente dovuto."
            else:
                defect = data["validation_feedback"]["defects"][0]
                assert defect["reason"] == "unsupported_draft"
                assert defect["support_reason"] == "Il rimborso non è automaticamente dovuto."
                assert defect["previous_fields"]["risk"] == "Il rimborso è automaticamente dovuto."
                assert data["documents"][0]["text"] == replay["documents"][0]["text"]
            return json.dumps(response)

    reviewer = RepairableDraft()
    result = review_grounded_flags(reviewer, replay["flags"][:1], replay["documents"], "it")
    assert len(reviewer.prompts) == 2
    assert "30 giorni dalla contestazione scritta" in result[0]["risk"]
    assert result[0]["grounding_reviewed"] is True
    assert result[0]["amount_eur"] == replay["flags"][0]["amount_eur"]
    assert "_draft_index" not in result[0]


@pytest.mark.parametrize("duplicate_quote", [False, True])
def test_changing_only_a_rejected_verdict_is_not_a_repair(replay, duplicate_quote):
    class VerdictFlip(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            if len(self.prompts) == 1:
                response[0]["supported"] = False
            elif duplicate_quote:
                response[0]["evidence"].append(copy.deepcopy(response[0]["evidence"][0]))
            return json.dumps(response)

    reviewer = VerdictFlip()
    with pytest.raises(LLMResponseError, match="without correcting.*draft 0, document 241"):
        review_grounded_flags(reviewer, replay["flags"][:1], replay["documents"], "it")
    assert len(reviewer.prompts) == 2


def test_unsupported_repair_must_still_pass_verbatim_verification(replay):
    class FabricatedRepair(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            if len(self.prompts) == 1:
                response[0].update(supported=False, evidence=[])
            else:
                response[0]["evidence"][0]["quote"] = "La banca conferma che il debito è già esigibile."
            return json.dumps(response)

    reviewer = FabricatedRepair()
    with pytest.raises(LLMResponseError, match="unsupported evidence after correction"):
        review_grounded_flags(reviewer, replay["flags"][:1], replay["documents"], "it")
    assert len(reviewer.prompts) == 2


def test_unrepairable_draft_is_dropped_and_reported_without_failing_the_others(replay):
    class RejectLoan(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            data = review_payload(prompt)
            if data["documents"][0]["document_id"] == 241:
                response[0].update(supported=False, support_reason="Il rimedio non risulta esercitato.")
            return json.dumps(response)

    reviewer = RejectLoan()
    flags = [replay["flags"][1], replay["flags"][0]]
    rejections = []
    result = review_grounded_flags(reviewer, flags, replay["documents"], "it", rejections=rejections)
    # One doubtful draft never discards the verified flags of the whole deal.
    assert [flag["source_document_id"] for flag in result] == [flags[0]["source_document_id"]]
    assert result[0]["grounding_reviewed"] is True
    assert len(rejections) == 1
    rejection = rejections[0]
    assert rejection["identity"] == "draft 1, document 241"
    assert rejection["reason"].startswith("could not support a draft after correction: draft 1, document 241")
    assert "Il rimedio non risulta esercitato." in rejection["reason"]
    assert flags[1]["title"] not in rejection["reason"]
    assert rejection["flag"]["title"] == flags[1]["title"]
    assert len(reviewer.prompts) == 3


def test_a_truncated_review_response_rejects_only_the_draft_that_caused_it(replay):
    """A reviewer that exhausts its output budget on one draft (e.g. by quoting a
    ledger) must not fail the whole aggregation: the batch is split and only
    the draft whose own review still fails is dropped, with the reason."""
    quote = "Non e documentata una richiesta di rimborso anticipato gia inviata dalla banca."

    class TruncatingOnLoan:
        def __init__(self):
            self.prompts = []

        def complete(self, prompt, max_tokens=2048):
            self.prompts.append(prompt)
            payload = review_payload(prompt)
            items = payload["items"]
            if any("DSCR" in item["candidate"]["title"] for item in items):
                raise LLMResponseError("AI response was truncated at the output token limit")
            doc_id = payload["documents"][0]["document_id"]
            return json.dumps([{
                "index": item["index"], "supported": True, "support_reason": None,
                "fields": {"title": "Nessuna richiesta di rimborso documentata",
                           "issue": "Non è documentata una richiesta di rimborso anticipato.",
                           "risk": None, "recommendation": None},
                "evidence": [{"source_document_id": doc_id, "quote": quote, "fields": ["title", "issue"]}],
            } for item in items])

    reviewer = TruncatingOnLoan()
    other = {"title": "Richiesta di rimborso", "issue": "Non è documentata una richiesta di rimborso anticipato.",
             "source_document_id": 241, "category": "liability", "severity": "low"}
    flags = [replay["flags"][0], other]
    rejections = []
    result = review_grounded_flags(reviewer, flags, replay["documents"], "it", rejections=rejections)
    assert [flag["title"] for flag in result] == ["Nessuna richiesta di rimborso documentata"]
    assert result[0]["grounding_reviewed"] is True
    assert len(rejections) == 1
    assert rejections[0]["identity"] == "draft 0, document 241"
    assert rejections[0]["reason"].startswith("review request failed: ")
    assert "truncated at the output token limit" in rejections[0]["reason"]
    # One failed batch call, then one call per half: the loan draft fails again
    # alone, the other draft is reviewed alone and kept.
    assert len(reviewer.prompts) == 3


def test_quotations_match_despite_accents_quotes_and_hyphenation():
    source = "L\u2019obbligazione \u00e8 sca-\nduta il 31/12/2024 e il \u201cgarante\u201d non ha pagato."

    class AsciiQuoter:
        def complete(self, prompt, max_tokens=2048):
            return json.dumps([{"index": 0, "supported": True, "support_reason": None,
                                "fields": {"title": "Obbligazione scaduta", "issue": "L'obbligazione e scaduta.",
                                           "risk": None, "recommendation": None},
                                "evidence": [{"source_document_id": 1,
                                              "quote": "L'obbligazione e scaduta il 31/12/2024 e il \"garante\" non ha pagato.",
                                              "fields": ["title", "issue"]}]}])

    rejections = []
    result = review_grounded_flags(AsciiQuoter(), [{"title": "Scadenza", "issue": "Scaduta.", "source_document_id": 1}],
                                   [{"document_id": 1, "text": source}], "it", rejections=rejections)
    assert rejections == []
    assert result[0]["grounding_reviewed"] is True
    assert len(result[0]["evidence"]) == 1


def test_a_window_without_the_evidence_cannot_reject_the_draft():
    text = "First paragraph.\n" + ("Boilerplate.\n" * 18000) + "LAST SOURCE LIMITATION."
    calls = []

    class RejectsIrrelevantWindows:
        def complete(self, prompt, max_tokens=2048):
            payload = review_payload(prompt)
            source = payload["documents"][0]["text"]
            calls.append("validation_feedback" in payload)
            fields = {"title": "Review", "issue": "A source issue.", "risk": None, "recommendation": None}
            if "LAST SOURCE LIMITATION." not in source:
                return json.dumps([{"index": 0, "supported": False, "fields": fields, "evidence": [],
                                    "support_reason": "The available text does not contain the passage."}])
            return json.dumps([{"index": 0, "supported": True, "support_reason": None, "fields": fields,
                                "evidence": [{"source_document_id": 1, "quote": "LAST SOURCE LIMITATION.",
                                              "fields": ["title", "issue"]}]}])

    rejections = []
    flags = review_grounded_flags(RejectsIrrelevantWindows(),
                                  [{"title": "Review", "issue": "A source issue.", "source_document_id": 1}],
                                  [{"document_id": 1, "text": text}], "en", rejections=rejections)
    assert rejections == []
    assert flags[0]["grounding_reviewed"] is True
    assert flags[0]["evidence"][0]["quote"] == "LAST SOURCE LIMITATION."
    # Every window is reviewed once; a negative verdict on an irrelevant
    # window never spends the correction budget.
    assert len(calls) > 1 and not any(calls)


def test_ledger_windows_are_located_by_the_names_and_amounts_the_draft_mentions():
    ledger_line = "AMCOR FLEXIBLES ARENZANO SRL 31/12/2020 saldo 3.883,00 INSOLUTO / RICHIAMO\n"
    text = ("Boilerplate.\n" * 8000) + ledger_line + ("Boilerplate.\n" * 8000)
    seen = []

    class LedgerReviewer:
        def complete(self, prompt, max_tokens=2048):
            payload = review_payload(prompt)
            source = payload["documents"][0]["text"]
            seen.append(len(prompt))
            assert "3.883,00" in source and "AMCOR FLEXIBLES" in source
            return json.dumps([{"index": 0, "supported": True, "support_reason": None,
                                "fields": {"title": "Credito Amcor Flexibles Arenzano Srl non incassato",
                                           "issue": "Saldo di 3.883,00 con insoluto e richiamo.",
                                           "risk": None, "recommendation": None},
                                "evidence": [{"source_document_id": 1, "quote": "saldo 3.883,00 INSOLUTO / RICHIAMO",
                                              "fields": ["title", "issue"]}]}])

    draft = {"title": "Credito Amcor Flexibles Arenzano Srl non incassato",
             "issue": "Saldo di 3.883,00 con insoluto e richiamo.", "source_document_id": 1}
    flags = review_grounded_flags(LedgerReviewer(), [draft], [{"document_id": 1, "text": text}], "it")
    assert flags[0]["grounding_reviewed"] is True
    # One bounded request around the located lines, not a sweep of the ledger.
    assert len(seen) == 1 and seen[0] < 20000


def test_every_draft_rejected_still_fails_closed(replay):
    class RejectAll(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            response[0]["supported"] = False
            return json.dumps(response)

    reviewer = RejectAll()
    with pytest.raises(LLMResponseError, match="rejected every draft.*draft 0, document 241.*draft 1, document 242"):
        review_grounded_flags(reviewer, replay["flags"], replay["documents"], "it")
    assert len(reviewer.prompts) == 4


def test_a_draft_no_window_can_support_is_dropped_while_the_other_survives():
    text = "First paragraph.\n" + ("Boilerplate.\n" * 18000) + "LAST SOURCE LIMITATION."

    class WindowReviewer:
        def complete(self, prompt, max_tokens=2048):
            payload = review_payload(prompt)
            source = payload["documents"][0]["text"]
            reviews = []
            for item in payload["items"]:
                candidate = item["candidate"]
                fields = {"title": candidate["title"], "issue": candidate["issue"],
                          "risk": None, "recommendation": None}
                if candidate["title"] == "Doubtful":
                    # No window ever holds a passage for this draft.
                    reviews.append({"index": item["index"], "supported": False,
                                    "support_reason": "Not in this window.",
                                    "fields": fields, "evidence": []})
                    continue
                reviews.append({"index": item["index"], "supported": True, "support_reason": None,
                                "fields": fields, "evidence": [{"source_document_id": 1, "quote": source[:16],
                                                                "fields": ["title", "issue"]}]})
            return json.dumps(reviews)

    rejections = []
    flags = review_grounded_flags(
        WindowReviewer(),
        [{"title": "Review", "issue": "A source issue.", "source_document_id": 1},
         {"title": "Doubtful", "issue": "An unsupported issue.", "source_document_id": 1}],
        [{"document_id": 1, "text": text}], "en", rejections=rejections)
    assert [flag["title"] for flag in flags] == ["Review"]
    assert flags[0]["grounding_reviewed"] is True
    assert [r["identity"] for r in rejections] == ["draft 1, document 1"]
    assert "without evidence" in rejections[0]["reason"]


def test_negative_review_schema_permits_missing_evidence_but_requires_explanation_field():
    from packages.agents.grounding_review import _review_item_schema
    schema = _review_item_schema("flags")
    assert "support_reason" in schema["required"]
    assert schema["properties"]["evidence"]["minItems"] == 0


@pytest.mark.parametrize("can_repair", [False, True])
def test_unsupported_draft_recovery_is_atomic_at_persistence(db, test_deal, replay, can_repair):
    from app.models.document import Document, DocumentStatus
    from app.models.red_flag import RedFlag, Severity
    from packages.agents.red_flag_aggregator import RedFlagAggregationAgent

    test_deal.report_language = "it"
    source = replay["documents"][0]
    document = Document(deal_id=test_deal.id, filename="loan.pdf", file_path="/tmp/loan.pdf",
                        mime_type="application/pdf", file_size=100, status=DocumentStatus.processed,
                        raw_text=source["text"])
    db.add(document)
    db.flush()
    draft = {**replay["flags"][0], "source_document_id": document.id}
    previous = RedFlag(deal_id=test_deal.id, title="Previous reviewed result", issue="Preserve me",
                       category="liability", severity=Severity.high)
    db.add(previous)
    db.commit()

    class RecoveringReviewer(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            if "GROUNDING REVIEW\n" in prompt and (len(self.prompts) == 1 or not can_repair):
                response[0].update(supported=False, evidence=[], support_reason="Mancano le condizioni del rimedio.")
            return json.dumps(response)

    reviewer = RecoveringReviewer([draft])
    if can_repair:
        result = RedFlagAggregationAgent(reviewer).run(test_deal.id, db)
        assert result["red_flags_count"] == 1
        current = db.query(RedFlag).filter_by(deal_id=test_deal.id).one()
        assert "30 giorni" in current.risk
        assert current.structured_payload_json["grounding_reviewed"] is True
    else:
        with pytest.raises(LLMResponseError, match="could not support.*after correction"):
            RedFlagAggregationAgent(reviewer).run(test_deal.id, db)
        assert db.query(RedFlag).filter_by(deal_id=test_deal.id).one().title == "Previous reviewed result"
    assert len(reviewer.prompts) == 2


def test_missing_field_links_receive_precise_feedback_and_complete_verification(replay):
    class OnceUnlinked(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            if len(self.prompts) == 1:
                for entry in response[0]["evidence"]:
                    entry["fields"] = ["title"]
            else:
                data = review_payload(prompt)
                assert data["validation_feedback"]["defects"][0]["missing_fields"] == ["issue", "risk"]
            return json.dumps(response)

    reviewer = OnceUnlinked()
    result = review_grounded_flags(reviewer, replay["flags"][:1], replay["documents"], "it")
    assert len(reviewer.prompts) == 2
    assert {field for entry in result[0]["evidence"] for field in entry["fields"]} >= {"title", "issue", "risk"}


def test_quote_and_coverage_repairs_share_the_same_single_retry_budget(replay):
    class TwoDefects(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            if len(self.prompts) == 1:
                response[0]["evidence"][0]["quote"] = "Invented quotation"
            else:
                for entry in response[0]["evidence"]:
                    entry["fields"] = ["title"]
            return json.dumps(response)

    reviewer = TwoDefects()
    with pytest.raises(LLMResponseError, match="without evidence"):
        review_grounded_flags(reviewer, replay["flags"][:1], replay["documents"], "it")
    assert len(reviewer.prompts) == 2


def test_empty_evidence_can_be_completed_only_by_a_verified_corrective_review(replay):
    class OnceEmpty(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            if len(self.prompts) == 1:
                response[0]["evidence"] = []
            else:
                data = review_payload(prompt)
                assert data["validation_feedback"]["defects"] == [{
                    "draft_index": 0, "missing_fields": ["issue", "risk", "title"],
                    "reason": "factual fields have no linked source quotations",
                }]
            return json.dumps(response)

    reviewer = OnceEmpty()
    result = review_grounded_flags(reviewer, replay["flags"][:1], replay["documents"], "it")
    assert len(reviewer.prompts) == 2
    assert result[0]["grounding_reviewed"] is True
    assert result[0]["evidence"]


def test_all_citation_and_coverage_defects_reach_the_single_corrective_review(replay):
    class MultipleDefects(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            second = copy.deepcopy(response[0])
            second["index"] = 1
            response.append(second)
            if len(self.prompts) == 1:
                response[0]["evidence"][0]["quote"] = "Invented quotation"
                response[0]["evidence"][1]["source_document_id"] = 999
                response[1]["evidence"] = []
            else:
                data = review_payload(prompt)
                defects = data["validation_feedback"]["defects"]
                assert len(defects) == 3
                assert [(d["draft_index"], d.get("evidence_index")) for d in defects] == [
                    (0, 0), (0, 1), (1, None)]
                assert defects[2]["missing_fields"] == ["issue", "risk", "title"]
            return json.dumps(response)

    reviewer = MultipleDefects()
    result = review_grounded_flags(reviewer, [replay["flags"][0]] * 2, replay["documents"], "it")
    assert len(reviewer.prompts) == 2
    assert len(result) == 2
    assert all(item["grounding_reviewed"] for item in result)


def test_irrelevant_partial_window_can_leave_evidence_empty():
    from packages.agents.grounding_review import _review

    class IrrelevantWindow:
        def complete(self, prompt, max_tokens=2048):
            return json.dumps([{"index": 0, "supported": True,
                                "fields": {"text": "A finding supported in another window."},
                                "evidence": []}])

    result = _review(IrrelevantWindow(), kind="text", candidates=[{"text": "A finding supported in another window."}],
                     documents=[{"document_id": 1, "text": "Unrelated source."}], language="en", partial=True)
    assert result[0]["evidence"] == []


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


def test_rejected_draft_becomes_an_open_question_and_verified_flags_replace_previous(db, test_deal, replay):
    from app.models.document import Document, DocumentStatus
    from app.models.open_question import OpenQuestion, Priority
    from app.models.red_flag import RedFlag, Severity
    from packages.agents.red_flag_aggregator import RedFlagAggregationAgent
    test_deal.report_language = "it"
    docs = replay["documents"]
    flags = copy.deepcopy(replay["flags"])
    for source, flag in zip(docs, flags):
        document = Document(deal_id=test_deal.id, filename=source["filename"], file_path="/tmp/fixture",
                            mime_type="application/pdf", file_size=100, status=DocumentStatus.processed,
                            raw_text=source["text"], page_count=source["page_count"])
        db.add(document)
        db.flush()
        flag["source_document_id"] = document.id
    loan_document_id = flags[0]["source_document_id"]
    db.add(RedFlag(deal_id=test_deal.id, title="Previous reviewed result", issue="Stale",
                   category="liability", severity=Severity.high))
    db.commit()

    class RejectLoan(ReplayReviewer):
        def complete(self, prompt, max_tokens=2048):
            response = json.loads(super().complete(prompt, max_tokens))
            if "GROUNDING REVIEW\n" in prompt:
                data = review_payload(prompt)
                if data["documents"][0]["document_id"] == loan_document_id:
                    response[0].update(supported=False, evidence=[],
                                       support_reason="Il rimborso non risulta richiesto.")
            return json.dumps(response)

    result = RedFlagAggregationAgent(RejectLoan(flags)).run(test_deal.id, db)
    assert result["red_flags_count"] == 1
    assert result["grounding_rejected"] == 1
    persisted = db.query(RedFlag).filter_by(deal_id=test_deal.id).all()
    assert [flag.title for flag in persisted] != ["Previous reviewed result"]
    assert len(persisted) == 1
    assert "non documentato" in persisted[0].title
    questions = db.query(OpenQuestion).filter_by(deal_id=test_deal.id, priority=Priority.medium).all()
    assert len(questions) == 1
    question = questions[0]
    assert question.agent_name == "red_flag_aggregation"
    assert question.document_id == loan_document_id
    assert question.question.startswith("Rilievo non pubblicato")
    assert flags[0]["title"] in question.question
    assert "Il rimborso non risulta richiesto." in question.question
    # The dropped narrative itself is not republished through the question.
    assert flags[0]["risk"] not in question.question


def test_summary_review_repairs_epistemic_drift_against_reviewed_findings():
    original = "I crediti sono privi di fondo svalutazione."
    source = "Non è indicato un fondo svalutazione per i crediti scaduti."

    class SummaryReviewer:
        def complete(self, prompt, max_tokens=2048):
            payload = review_payload(prompt)
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
            payload = review_payload(prompt)
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
            payload = review_payload(prompt)
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
            payload = review_payload(prompt)
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


def test_document_groups_are_reviewed_in_parallel_and_reported_in_input_order(replay):
    """Two document groups must be in flight at the same time.

    Reviewing one group at a time on the judgment model took a 169-draft data
    room past the worker's job timeout. The barrier trips only if both groups'
    first review requests overlap; verdicts still land in input order.
    """
    import threading

    class OverlappingReviewer(ReplayReviewer):
        def __init__(self):
            super().__init__()
            self.barrier = threading.Barrier(2, timeout=5)
            self.first_seen = set()
            self.lock = threading.Lock()

        def complete(self, prompt, max_tokens=2048):
            if "GROUNDING REVIEW\n" in prompt:
                doc_id = review_payload(prompt)["documents"][0]["document_id"]
                with self.lock:
                    first = doc_id not in self.first_seen
                    self.first_seen.add(doc_id)
                if first:
                    self.barrier.wait()  # BrokenBarrierError if reviewed sequentially
            return super().complete(prompt, max_tokens)

    reviewer = OverlappingReviewer()
    flags = [replay["flags"][1], replay["flags"][0]]
    result = review_grounded_flags(reviewer, flags, replay["documents"], "it")
    assert [flag["source_document_id"] for flag in result] == [flag["source_document_id"] for flag in flags]
    assert all(flag["grounding_reviewed"] for flag in result)
    assert reviewer.first_seen == {flag["source_document_id"] for flag in flags}


def test_a_draft_citing_a_foreign_document_fails_before_any_review_request(replay):
    reviewer = ReplayReviewer()
    flags = [replay["flags"][0], {**replay["flags"][1], "evidence": [{"source_document_id": 999999, "quote": "x"}]}]
    with pytest.raises(LLMResponseError, match="outside this deal"):
        review_grounded_flags(reviewer, flags, replay["documents"], "it")
    assert reviewer.prompts == []


def test_review_prompt_is_segmented_so_the_sources_are_a_reusable_prefix(replay):
    """Instructions and sources form the cacheable head, byte-identical between
    the first pass and the correction pass of the same batch; the drafts and
    the feedback are the unmarked tail. Joined, the halves are still the one
    JSON payload the reviewer has always received."""

    class SegmentRecorder(ReplayReviewer):
        supports_prompt_segments = True

        def __init__(self):
            super().__init__()
            self.segmented = []
            self.rejected_once = False

        def complete_json(self, prompt, max_tokens=2048, *, response_type="array", item_schema=None):
            assert not isinstance(prompt, str)
            self.segmented.append(tuple(prompt))
            response = json.loads(super().complete(prompt_text(prompt), max_tokens))
            if not self.rejected_once:
                # First pass: no quotations, so a correction pass follows.
                self.rejected_once = True
                response[0]["evidence"] = []
            return json.dumps(response)

    reviewer = SegmentRecorder()
    flags = [replay["flags"][1]]
    result = review_grounded_flags(reviewer, flags, replay["documents"], "it")
    assert len(result) == 1 and result[0]["grounding_reviewed"] is True
    first, correction = reviewer.segmented
    for segments in (first, correction):
        assert [segment.cache for segment in segments] == [True, True, False]
        assert segments[0].text.startswith("GROUNDING REVIEW\n")
        payload = review_payload(prompt_text(segments))
        assert list(payload)[:3] == ["kind", "language", "documents"]
        assert "items" in payload
    # Both cached blocks are reused by the correction pass: the corrective
    # instruction rides in the unmarked tail, behind them, so the source block
    # is read back instead of being written to the cache a second time.
    assert first[0] == correction[0]
    assert first[1] == correction[1]
    assert first[2] != correction[2]
    assert "CORRECTION PASS" not in first[2].text
    assert correction[2].text.rstrip().endswith("to obtain a positive verdict.")
    assert "validation_feedback" in review_payload(prompt_text(correction))


def test_batches_of_one_document_run_in_order_while_documents_run_in_parallel():
    """Two batches of the same source must not be in flight at once.

    They share their whole source block, so running them in order lets the
    second read what the first put in the provider's prompt cache. Run
    together they both miss, and a long document is written to the cache once
    per batch at the write premium. Different documents still overlap.
    """
    import threading

    documents = [{"document_id": 1, "text": "ALPHA CLAUSE."}, {"document_id": 2, "text": "BETA CLAUSE."}]
    quotes = {1: "ALPHA CLAUSE.", 2: "BETA CLAUSE."}

    class Recorder:
        def __init__(self):
            self.lock = threading.Lock()
            self.in_flight = set()
            self.overlapped = []
            self.started = set()
            self.barrier = threading.Barrier(2, timeout=5)

        def complete(self, prompt, max_tokens=2048):
            payload = review_payload(prompt)
            doc_id = payload["documents"][0]["document_id"]
            with self.lock:
                if doc_id in self.in_flight:
                    self.overlapped.append(doc_id)
                self.in_flight.add(doc_id)
                first = doc_id not in self.started
                self.started.add(doc_id)
            if first:
                self.barrier.wait()  # BrokenBarrierError if documents were serialised
            try:
                return json.dumps([
                    {"index": item["index"], "supported": True, "support_reason": None,
                     "fields": {"title": "Rilievo", "issue": "Il documento riporta la clausola.",
                                "risk": None, "recommendation": None},
                     "evidence": [{"source_document_id": doc_id, "quote": quotes[doc_id],
                                   "fields": ["title", "issue"]}]}
                    for item in payload["items"]
                ])
            finally:
                with self.lock:
                    self.in_flight.discard(doc_id)

    flags = [{"title": "Rilievo", "issue": "Il documento riporta la clausola.", "source_document_id": 1}
             for _ in range(9)]
    flags.append({"title": "Rilievo", "issue": "Il documento riporta la clausola.", "source_document_id": 2})

    reviewer = Recorder()
    result = review_grounded_flags(reviewer, flags, documents, "it")
    assert len(result) == 10 and all(flag["grounding_reviewed"] for flag in result)
    # Nine drafts on document 1 exceed the batch size, so it is reviewed twice.
    assert reviewer.overlapped == []
    assert reviewer.started == {1, 2}


def _long_bylaws():
    """A statuto long enough to be reviewed in windows, as the Arcari one is.

    The company name recurs in every article, so the name locator only ever
    reaches the first few; the article a draft is about sits deep in the text.
    """
    articles = []
    for number in range(1, 31):
        body = (f"ARCARI S.R.L. disciplina in questo articolo la materia numero {number}. " * 24)
        if number == 8:
            body += ("Le quote sono trasferibili solo previo esercizio del diritto di prelazione "
                     "spettante agli altri soci, da esercitarsi entro trenta giorni dalla comunicazione. ")
        if number == 21:
            body += ("Qualsiasi controversia tra i soci sarà devoluta ad un arbitro unico nominato "
                     "dal Presidente del Tribunale, ai sensi dell'art. 34 del D.Lgs. 5/2003. ")
        if number == 25:
            body += "Si applica quanto previsto dall'art. 2477 c.c. in materia di organo di controllo. "
        articles.append(f"\nArticolo {number} - Materia {number}\n{body}")
    text = "".join(articles)
    assert len(text) > 40_000
    return text


def test_a_draft_about_an_article_is_shown_that_article_of_a_long_statute():
    """The review of a long statuto must see the article the draft is about.

    On the Arcari run five findings from the new statuto (pre-emption, consent
    clause, withdrawal value, arbitration) were rejected with "the available
    extract does not contain art. 8": the windows followed the company name,
    which fills the first articles, and never reached article 8.
    """
    from packages.agents.grounding_review import _review_sources

    text = _long_bylaws()
    document = {"document_id": 188, "text": text}
    draft = {"title": "Prelazione sulle quote (art. 8 dello statuto)",
             "issue": "L'art. 8 dello statuto di ARCARI S.R.L. prevede un diritto di prelazione.",
             "source_document_id": 188}
    window = _review_sources([document], [draft])[0]["review_text"]
    assert "diritto di prelazione" in window
    assert "Articolo 8 - Materia 8" in window


def test_article_references_do_not_bleed_into_longer_numbers():
    """An article locator narrows the review to that article, not to its neighbours.

    Without any locator the review sweeps the whole statuto window by window;
    "art. 21" must reach article 21 without pulling article 2 in by prefix.
    """
    from packages.agents.grounding_review import _review_sources

    text = _long_bylaws()
    draft = {"title": "Clausola compromissoria",
             "issue": "L'articolo 21 devolve le controversie ad un arbitro unico.",
             "source_document_id": 188}
    window = _review_sources([{"document_id": 188, "text": text}], [draft])[0]["review_text"]
    assert "arbitro unico" in window
    # Article 2 is not article 21, and article 21 is not article 210.
    assert "Articolo 2 - Materia 2\n" not in window


def test_a_civil_code_reference_locates_where_the_statute_cites_it():
    from packages.agents.grounding_review import _review_sources

    text = _long_bylaws()
    draft = {"title": "Organo di controllo",
             "issue": "Lo statuto di ARCARI S.R.L. richiama l'art. 2477 c.c. per la nomina "
                      "dell'organo di controllo.",
             "source_document_id": 188}
    window = _review_sources([{"document_id": 188, "text": text}], [draft])[0]["review_text"]
    assert "dall'art. 2477 c.c. in materia di organo di controllo" in window


def test_a_pre_emption_finding_on_a_long_statute_now_survives_the_review():
    """End to end: the Arcari failure, replayed, now ends in a verified flag."""
    text = _long_bylaws()
    clause = ("Le quote sono trasferibili solo previo esercizio del diritto di prelazione "
              "spettante agli altri soci, da esercitarsi entro trenta giorni dalla comunicazione.")
    prompts = []

    class StatuteReviewer:
        def complete(self, prompt, max_tokens=2048):
            payload = review_payload(prompt)
            source = payload["documents"][0]["text"]
            prompts.append(len(prompt))
            fields = {"title": "Prelazione sulle quote (art. 8 dello statuto)",
                      "issue": "Le quote sono trasferibili solo previo esercizio della prelazione.",
                      "risk": None, "recommendation": None}
            if clause not in source:
                return json.dumps([{"index": 0, "supported": False, "fields": fields, "evidence": [],
                                    "support_reason": "L'estratto disponibile non contiene l'art. 8."}])
            return json.dumps([{"index": 0, "supported": True, "support_reason": None, "fields": fields,
                                "evidence": [{"source_document_id": 188, "quote": clause,
                                              "fields": ["title", "issue"]}]}])

    draft = {"title": "Prelazione sulle quote (art. 8 dello statuto)",
             "issue": "L'art. 8 dello statuto di ARCARI S.R.L. subordina il trasferimento alla prelazione.",
             "source_document_id": 188}
    rejections = []
    flags = review_grounded_flags(StatuteReviewer(), [draft], [{"document_id": 188, "text": text}],
                                  "it", rejections=rejections)
    assert rejections == []
    assert flags[0]["grounding_reviewed"] is True
    assert flags[0]["evidence"][0]["quote"] == clause
    # One focused request on the located articles, not a sweep of the statuto.
    assert len(prompts) == 1 and prompts[0] < len(text)
