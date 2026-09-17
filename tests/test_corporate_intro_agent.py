"""Tests for the corporate intro extraction agent.

Exercise the auto-detection (only corporate-looking documents get LLM'd),
the persistence shape (CompanyProfile row with the standard fields), and
idempotency (re-running clears previous rows).
"""
from __future__ import annotations

import json

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
                        "company_name": "Maybe Co",
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
