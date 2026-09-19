"""Tests for the corporate intro extraction agent.

Exercise the auto-detection (only corporate-looking documents get LLM'd),
the persistence shape (CompanyProfile row with the standard fields), and
idempotency (re-running clears previous rows).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.company_profile import CompanyProfile
from app.models.deal import Deal
from app.models.document import Document, DocumentStatus
from packages.agents.corporate_intro_agent import (
    AGENT_NAME,
    CorporateIntroAgent,
    run_corporate_intro_extraction,
)
from packages.agents.deal_analysis_agent import FakeLLMProvider, set_llm_provider


@pytest.fixture(autouse=True)
def _fake_llm():
    set_llm_provider(FakeLLMProvider())


@pytest.fixture(autouse=True)
def _confirmed_target(db, test_deal):
    test_deal.target_company_names = ["TargetCo S.p.A."]
    db.commit()


def _make_doc(
    db: Session,
    deal: Deal,
    *,
    filename: str = "statuto_sociale.pdf",
    raw_text: str = "Statuto sociale della Società.",
) -> Document:
    doc = Document(
        deal_id=deal.id,
        filename=filename,
        file_path=f"deals/{deal.id}/{filename}",
        mime_type="application/pdf",
        file_size=100,
        status=DocumentStatus.processed,
        raw_text=raw_text,
        page_count=1,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


# ── auto-detection ────────────────────────────────────────────────────────


class TestAutoDetection:

    def test_corporate_filename_matches(self, db, test_deal):
        _make_doc(db, test_deal, filename="visura_camerale.pdf", raw_text="Visura camerale")
        result = CorporateIntroAgent().run(test_deal.id, db)
        assert result["documents_analysed"] == 1
        assert result["company_profiles_count"] == 1

    def test_non_corporate_document_skipped(self, db, test_deal):
        _make_doc(db, test_deal, filename="invoice.pdf", raw_text="Invoice for services rendered.")
        result = CorporateIntroAgent().run(test_deal.id, db)
        assert result["documents_analysed"] == 0
        assert result["company_profiles_count"] == 0

    def test_explicit_document_ids_bypasses_keyword_filter(self, db, test_deal):
        # File looks unrelated but caller forces it in.
        doc = _make_doc(db, test_deal, filename="something.pdf", raw_text="text")
        result = CorporateIntroAgent().run(test_deal.id, db, document_ids={doc.id})
        assert result["documents_analysed"] == 1


@pytest.mark.parametrize("text", [
    "Sede legale: Milano. Capitale sociale: EUR 100.000. Assetto proprietario: Holding Srl 100%.",
    "Registered office: London. Share capital: GBP 100,000. Board of directors: Jane Example.",
    "Sede\nlegale: Roma. Capitale\nsociale: EUR 10.000. Amministratrice\nunica: Elena Esempio.",
])
def test_corporate_facts_select_generic_filenames(text):
    assert CorporateIntroAgent._looks_corporate(SimpleNamespace(filename="documento.pdf", raw_text=text))


@pytest.mark.parametrize("text", [
    "Invoice 100. Company name: TargetCo S.p.A. Amount EUR 100.",
    "Fattura. Sede legale: Milano. Capitale sociale: EUR 100.000.",
    "Capitale sociale EUR 10.000. Capitale sociale EUR 10.000. Capitale sociale EUR 10.000.",
])
def test_isolated_or_repeated_company_fields_do_not_select_unrelated_files(text):
    assert not CorporateIntroAgent._looks_corporate(SimpleNamespace(filename="documento.pdf", raw_text=text))


def test_late_corporate_profile_is_not_lost_to_excerpt_or_window_boundary():
    # The heading straddles the end of the first 12k selection window, after
    # the old 1,500-character excerpt. The overlap must retain the whole label.
    text = "Introduction. " * 920
    text = text[:11996] + "Profilo\nsocietario della target. Aurora Collaudo S.r.l."
    assert CorporateIntroAgent._looks_corporate(SimpleNamespace(filename="allegati.pdf", raw_text=text))


def test_late_corporate_fields_select_without_a_profile_heading():
    text = "Informazioni generali. " * 1400
    text += "\nSede legale: Milano. Capitale sociale: EUR 100.000. Amministratrice unica: Elena Esempio."
    assert CorporateIntroAgent._looks_corporate(SimpleNamespace(filename="allegati.pdf", raw_text=text))


def test_live_sample_profile_is_extracted_without_promoting_buyer_or_seller(db, test_deal):
    corpus = json.loads((Path(__file__).parent / "fixtures" / "live_sample_2026_09_19.json").read_text(encoding="utf-8"))
    test_deal.target_company_names = ["Aurora Collaudo S.r.l."]
    db.commit()
    documents = {
        filename: _make_doc(db, test_deal, filename=filename, raw_text="\n".join(pages))
        for filename, pages in corpus.items()
    }
    prompts = []

    class SampleProvider(FakeLLMProvider):
        def complete(self, prompt, max_tokens=2048):
            prompts.append(prompt)
            assert "Questo profilo non ne attesta la regolarita" in prompt
            assert '["Aurora Collaudo S.r.l."]' in prompt
            return json.dumps([
                {
                    "company_name": "Aurora Collaudo S.r.l.",
                    "registered_office": "Milano, Via del Collaudo 10",
                    "corporate_capital": "EUR 100.000,00 interamente versato",
                    "shareholders": "Prisma Collaudo Holding S.r.l. — 100%",
                    "managing_body": "Elena Esempio (amministratrice unica)",
                    "confidence": 0.95,
                },
                {"company_name": "Prisma Collaudo Holding S.r.l.", "confidence": 0.99},
                {"company_name": "Quercia Collaudo Investimenti S.p.A.", "confidence": 0.99},
            ])

    result = CorporateIntroAgent(provider=SampleProvider()).run(test_deal.id, db)
    assert result["documents_analysed"] == 1
    assert result["company_profiles_count"] == 1
    assert len(prompts) == 1
    saved = db.query(CompanyProfile).filter_by(deal_id=test_deal.id).one()
    assert saved.company_name == "Aurora Collaudo S.r.l."
    assert saved.source_document_id == documents["01_profilo_societario.pdf"].id
    assert saved.registered_office == "Milano, Via del Collaudo 10"
    assert saved.corporate_capital == "EUR 100.000,00 interamente versato"
    assert saved.shareholders == "Prisma Collaudo Holding S.r.l. — 100%"
    assert saved.managing_body == "Elena Esempio (amministratrice unica)"
    assert saved.auditors is None


# ── persistence ───────────────────────────────────────────────────────────


class TestPersistence:

    def test_company_profile_row_created(self, db, test_deal):
        _make_doc(db, test_deal, filename="statuto.pdf")
        run_corporate_intro_extraction(test_deal.id, db)
        profiles = db.query(CompanyProfile).filter(
            CompanyProfile.deal_id == test_deal.id
        ).all()
        assert len(profiles) == 1
        assert profiles[0].company_name  # Required field populated.

    def test_standard_fields_populated(self, db, test_deal):
        _make_doc(db, test_deal, filename="statuto.pdf")
        run_corporate_intro_extraction(test_deal.id, db)
        p = db.query(CompanyProfile).filter(
            CompanyProfile.deal_id == test_deal.id
        ).first()
        assert p.legal_form
        assert p.corporate_capital
        assert p.business
        assert p.confidence is not None

    def test_source_document_id_recorded(self, db, test_deal):
        doc = _make_doc(db, test_deal, filename="statuto.pdf")
        run_corporate_intro_extraction(test_deal.id, db)
        p = db.query(CompanyProfile).filter(
            CompanyProfile.deal_id == test_deal.id
        ).first()
        assert p.source_document_id == doc.id

    def test_agent_run_records_completed(self, db, test_deal):
        _make_doc(db, test_deal, filename="statuto.pdf")
        run_corporate_intro_extraction(test_deal.id, db)
        run = db.query(AgentRun).filter(
            AgentRun.deal_id == test_deal.id,
            AgentRun.agent_name == AGENT_NAME,
        ).one()
        assert run.status == AgentRunStatus.completed
        assert run.started_at is not None
        assert run.completed_at is not None


# ── idempotency ───────────────────────────────────────────────────────────


class TestIdempotency:

    def test_rerun_replaces_profiles(self, db, test_deal):
        _make_doc(db, test_deal, filename="statuto.pdf")
        run_corporate_intro_extraction(test_deal.id, db)
        run_corporate_intro_extraction(test_deal.id, db)
        profiles = db.query(CompanyProfile).filter(
            CompanyProfile.deal_id == test_deal.id
        ).all()
        # Same document still yields exactly one profile after re-run.
        assert len(profiles) == 1

    def test_rerun_replaces_agent_run(self, db, test_deal):
        _make_doc(db, test_deal, filename="statuto.pdf")
        run_corporate_intro_extraction(test_deal.id, db)
        run_corporate_intro_extraction(test_deal.id, db)
        runs = db.query(AgentRun).filter(
            AgentRun.deal_id == test_deal.id,
            AgentRun.agent_name == AGENT_NAME,
        ).all()
        assert len(runs) == 1


# ── degraded LLM input ────────────────────────────────────────────────────


class TestDegradedInput:

    def test_low_confidence_profile_dropped(self, db, test_deal):
        _make_doc(db, test_deal, filename="statuto.pdf")

        class LowConfLLM(FakeLLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "CORPORATE INTRODUCTORY INFORMATION" in prompt.upper():
                    return json.dumps([{
                        "company_name": "TargetCo S.p.A.",
                        "confidence": 0.30,
                    }])
                return super().complete(prompt, max_tokens)

        result = CorporateIntroAgent(provider=LowConfLLM()).run(test_deal.id, db)
        assert result["company_profiles_count"] == 0

    def test_missing_company_name_dropped(self, db, test_deal):
        _make_doc(db, test_deal, filename="statuto.pdf")

        class NoNameLLM(FakeLLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "CORPORATE INTRODUCTORY INFORMATION" in prompt.upper():
                    return json.dumps([{"confidence": 0.9}])
                return super().complete(prompt, max_tokens)

        result = CorporateIntroAgent(provider=NoNameLLM()).run(test_deal.id, db)
        assert result["company_profiles_count"] == 0

    def test_unparseable_llm_output_fails_stage(self, db, test_deal):
        _make_doc(db, test_deal, filename="statuto.pdf")

        class BrokenLLM(FakeLLMProvider):
            def complete(self, prompt: str, max_tokens: int = 2048) -> str:
                if "CORPORATE INTRODUCTORY INFORMATION" in prompt.upper():
                    return "not json at all"
                return super().complete(prompt, max_tokens)

        from packages.agents.deal_analysis_agent import LLMResponseError

        with pytest.raises(LLMResponseError):
            CorporateIntroAgent(provider=BrokenLLM()).run(test_deal.id, db)


def test_missing_scope_skips_all_llm_calls_and_keeps_raw_prior_evidence(db, test_deal):
    doc = _make_doc(db, test_deal, filename="visura.pdf")
    previous = CompanyProfile(deal_id=test_deal.id, company_name="Previous Srl", source_document_id=doc.id)
    db.add(previous)
    test_deal.target_company_names = None
    db.commit()

    class NeverCalled(FakeLLMProvider):
        def complete(self, *args, **kwargs):
            raise AssertionError("Missing target scope must not invoke a provider")

    result = CorporateIntroAgent(provider=NeverCalled()).run(test_deal.id, db, document_ids={doc.id})
    assert result["documents_analysed"] == 0
    assert result["company_profiles_count"] == 0
    assert db.query(CompanyProfile).filter_by(deal_id=test_deal.id).one().id == previous.id


def test_scope_is_in_every_batch_and_counterparties_are_hard_filtered(db, test_deal):
    _make_doc(db, test_deal, filename="visura.pdf", raw_text="Corporate facts.\n" * 1700)
    prompts = []

    class MultipleCompanies(FakeLLMProvider):
        def complete(self, prompt, max_tokens=2048):
            prompts.append(prompt)
            assert max_tokens == 6144
            return json.dumps([
                {"company_name": "TARGETCO SPA", "confidence": 0.9, "shareholders": "Holding Srl — 100%"},
                {"company_name": "Customer Srl", "confidence": 0.99},
                {"company_name": "Holding Srl", "confidence": 0.99},
                {"company_name": "TargetCo Servizi Spa", "confidence": 0.99},
                {"company_name": "TargetCo Srl", "confidence": 0.99},
            ])

    result = CorporateIntroAgent(provider=MultipleCompanies()).run(test_deal.id, db)
    assert len(prompts) >= 3
    assert all('["TargetCo S.p.A."]' in prompt for prompt in prompts)
    assert result["company_profiles_count"] == 1
    saved = db.query(CompanyProfile).filter_by(deal_id=test_deal.id).one()
    assert saved.company_name == "TARGETCO SPA"
    assert saved.shareholders == "Holding Srl — 100%"


def test_persistence_rechecks_scope_even_if_batch_layer_returns_foreign_company(db, test_deal, monkeypatch):
    _make_doc(db, test_deal, filename="visura.pdf")
    agent = CorporateIntroAgent()
    monkeypatch.setattr(agent, "_profile_payloads", lambda *args: [
        {"company_name": "Supplier Srl", "confidence": 0.99},
        {"company_name": "TargetCo S.P.A.", "confidence": 0.9},
    ])
    assert agent.run(test_deal.id, db)["company_profiles_count"] == 1
    assert db.query(CompanyProfile).filter_by(deal_id=test_deal.id).one().company_name == "TargetCo S.P.A."


def test_distinct_target_companies_and_per_document_evidence_are_retained(db, test_deal):
    from packages.agents.company_identity import consolidate_company_profiles

    test_deal.target_company_names = ["TargetCo S.p.A.", "Second Srl"]
    db.commit()
    docs = [_make_doc(db, test_deal, filename="visura.pdf"), _make_doc(db, test_deal, filename="statuto.pdf")]

    class TwoTargets(FakeLLMProvider):
        def complete(self, prompt, max_tokens=2048):
            return json.dumps([{"company_name": "TargetCo SPA", "confidence": 0.9},
                               {"company_name": "Second S.R.L.", "confidence": 0.9}])

    agent = CorporateIntroAgent(provider=TwoTargets())
    assert agent.run(test_deal.id, db)["company_profiles_count"] == 4
    rows = db.query(CompanyProfile).filter_by(deal_id=test_deal.id).all()
    assert len(rows) == 4
    views = consolidate_company_profiles(rows, test_deal.target_company_names)
    assert len(views) == 2
    assert all(view.source_document_ids == sorted(doc.id for doc in docs) for view in views)
    assert agent.run(test_deal.id, db)["company_profiles_count"] == 4
    assert db.query(CompanyProfile).filter_by(deal_id=test_deal.id).count() == 4


def test_failed_scoped_extraction_preserves_prior_profiles(db, test_deal):
    _make_doc(db, test_deal, filename="visura.pdf")
    run_corporate_intro_extraction(test_deal.id, db)
    previous_id = db.query(CompanyProfile).filter_by(deal_id=test_deal.id).one().id

    class FailingProvider(FakeLLMProvider):
        def complete(self, *args, **kwargs):
            raise RuntimeError("Synthetic provider failure")

    with pytest.raises(RuntimeError, match="Synthetic provider failure"):
        CorporateIntroAgent(provider=FailingProvider()).run(test_deal.id, db)
    assert db.query(CompanyProfile).filter_by(deal_id=test_deal.id).one().id == previous_id


def test_conflicting_values_in_one_long_document_remain_distinct_evidence(db, test_deal):
    from packages.agents.company_identity import consolidate_company_profiles

    doc = _make_doc(db, test_deal, filename="statuto.pdf", raw_text=(
        "FIRST_CAPITAL\n" + "Corporate facts.\n" * 1800 + "LAST_CAPITAL"))

    class ConflictingParts(FakeLLMProvider):
        def complete(self, prompt, max_tokens=2048):
            if "FIRST_CAPITAL" in prompt:
                return json.dumps([{"company_name": "TargetCo S.p.A.", "confidence": 0.9,
                                    "corporate_capital": "EUR 10,000", "registered_office": "Milano"}])
            if "LAST_CAPITAL" in prompt:
                return json.dumps([{"company_name": "TargetCo S.p.A.", "confidence": 0.9,
                                    "corporate_capital": "EUR 20,000", "registered_office": "Roma"}])
            return "[]"

    CorporateIntroAgent(provider=ConflictingParts()).run(test_deal.id, db)
    rows = db.query(CompanyProfile).filter_by(deal_id=test_deal.id).all()
    assert len(rows) == 2
    view = consolidate_company_profiles(rows, test_deal.target_company_names)[0]
    assert set(view.conflicting_fields) == {"corporate_capital", "registered_office"}
    assert {item["value"] for item in view.field_sources["corporate_capital"]} == {"EUR 10,000", "EUR 20,000"}
    assert all(item["source_document_ids"] == [doc.id] for item in view.field_sources["corporate_capital"])
