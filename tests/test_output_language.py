"""Output-language resolution and localized report rendering."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models.deal import Deal
from app.models.document import Document, DocumentStatus
from packages.agents.deal_analysis_agent import FakeLLMProvider, set_llm_provider
from packages.agents.output_language import resolve_output_language
from packages.agents.report_agent import generate_due_diligence_report
from tests.report_fixtures import complete_report_inputs


@pytest.fixture(autouse=True)
def _fake_llm():
    set_llm_provider(FakeLLMProvider())


def _doc(db: Session, deal: Deal, language: str | None, n: int = 0) -> Document:
    d = Document(
        deal_id=deal.id,
        filename=f"doc{n}.pdf",
        file_path=f"deals/{deal.id}/doc{n}.pdf",
        mime_type="application/pdf",
        file_size=10,
        status=DocumentStatus.processed,
        language=language,
        raw_text="contenuto",
        page_count=1,
    )
    db.add(d)
    db.commit()
    return d


class TestResolution:

    def test_explicit_override_wins(self, db, test_deal):
        test_deal.report_language = "it"
        db.commit()
        _doc(db, test_deal, "en")
        assert resolve_output_language(test_deal, db) == "it"

    def test_majority_italian_documents(self, db, test_deal):
        _doc(db, test_deal, "it", 1)
        _doc(db, test_deal, "it", 2)
        _doc(db, test_deal, "en", 3)
        assert resolve_output_language(test_deal, db) == "it"

    def test_majority_english_documents(self, db, test_deal):
        _doc(db, test_deal, "en", 1)
        _doc(db, test_deal, "en", 2)
        _doc(db, test_deal, "it", 3)
        assert resolve_output_language(test_deal, db) == "en"

    def test_no_documents_falls_back_to_english(self, db, test_deal):
        assert resolve_output_language(test_deal, db) == "en"

    def test_unknown_language_ignored(self, db, test_deal):
        _doc(db, test_deal, "de", 1)
        _doc(db, test_deal, None, 2)
        assert resolve_output_language(test_deal, db) == "en"


class TestItalianReport:

    def test_italian_headings_when_docs_italian(self, db, test_deal):
        _doc(db, test_deal, "it", 1)
        complete_report_inputs(db, test_deal)
        md = generate_due_diligence_report(test_deal.id, db)["markdown"]
        # Section numbering (1., 1.1, ...) is applied at render time.
        assert "## 1. Introduzione" in md
        assert "### 1.1 Scopo della Relazione" in md
        assert "_STRETTAMENTE CONFIDENZIALE_" in md
        # The Allegato keeps its roman numeral (skipped by the numbering pass).
        assert "## Allegato I: Lista dei Documenti Esaminati" in md
        # Per the bilingual practice in professional reports, these stay English:
        assert "Executive Summary" in md
        assert "Key Findings" in md

    def test_italian_via_explicit_override(self, db, test_deal):
        test_deal.report_language = "it"
        db.commit()
        _doc(db, test_deal, "en", 1)  # docs English, override wins
        complete_report_inputs(db, test_deal)
        md = generate_due_diligence_report(test_deal.id, db)["markdown"]
        assert "## 1. Introduzione" in md

    def test_english_report_unchanged(self, db, test_deal):
        _doc(db, test_deal, "en", 1)
        complete_report_inputs(db, test_deal)
        md = generate_due_diligence_report(test_deal.id, db)["markdown"]
        assert "## 1. Introduction" in md
        assert "_STRICTLY PRIVATE AND CONFIDENTIAL_" in md
        assert "## Appendix I: Documents Reviewed" in md


class TestPatchEndpoint:

    def test_set_language_via_patch(self, client, auth_headers, test_deal):
        r = client.patch(
            f"/deals/{test_deal.id}",
            json={"report_language": "it"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["report_language"] == "it"

    def test_auto_clears_override(self, client, auth_headers, test_deal):
        client.patch(
            f"/deals/{test_deal.id}",
            json={"report_language": "it"},
            headers=auth_headers,
        )
        r = client.patch(
            f"/deals/{test_deal.id}",
            json={"report_language": "auto"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["report_language"] is None

    def test_invalid_language_rejected(self, client, auth_headers, test_deal):
        r = client.patch(
            f"/deals/{test_deal.id}",
            json={"report_language": "fr"},
            headers=auth_headers,
        )
        assert r.status_code == 422
