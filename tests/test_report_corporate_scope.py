"""The corporate introduction is scoped, consolidated and safely refreshable."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from packages.agents.report_agent import (
    _render_corporate_intro,
    refresh_corporate_intro_section,
)


def _profile(name="Alfa S.r.l.", *, identity=1, document=10, filename="visura.pdf", **fields):
    return SimpleNamespace(
        id=identity, deal_id=4, company_name=name,
        source_document_id=document, source_filename=filename,
        confidence=0.9, created_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
        **fields,
    )


def test_one_target_from_two_documents_has_one_table_and_combined_fields():
    profiles = [
        _profile(registered_office="Milano"),
        _profile("ALFA SRL", identity=2, document=11, filename="statuto.pdf", corporate_capital="EUR 10,000"),
        _profile("Cliente S.r.l.", identity=3, document=12, business="Cliente estraneo"),
        _profile("Fornitore S.p.A.", identity=4, document=13, business="Fornitore estraneo"),
        _profile("Alfa Servizi S.r.l.", identity=5, document=14, business="Non è il target"),
    ]

    markdown = _render_corporate_intro(profiles, "it", ["Alfa S.r.l."])

    assert markdown.count("### ") == 1
    assert markdown.count("| Campo | Valore |") == 1
    assert "Milano" in markdown and "EUR 10,000" in markdown
    assert "visura.pdf" in markdown and "statuto.pdf" in markdown
    assert "Cliente" not in markdown and "Fornitore" not in markdown
    assert "Alfa Servizi" not in markdown
    assert "valori diversi" not in markdown
    assert profiles[0].registered_office == "Milano"
    assert not hasattr(profiles[0], "corporate_capital")


def test_two_explicit_targets_stay_separate_and_follow_scope_order():
    profiles = [_profile("Alfa S.r.l."), _profile("Alfa S.p.A.", identity=2)]
    markdown = _render_corporate_intro(profiles, "en", ["Alfa SPA", "Alfa SRL"])
    assert markdown.count("### ") == 2
    assert markdown.index("### Alfa SPA") < markdown.index("### Alfa SRL")


@pytest.mark.parametrize("lang,label,warning", [
    ("it", "Capitale Sociale", "richiede verifica"),
    ("en", "Corporate Capital", "requires verification"),
])
def test_a_conflict_is_one_line_under_the_table_not_a_list_of_alternatives(lang, label, warning):
    """Listing every other rendering with its document repeated the introduction."""
    profiles = [
        _profile(corporate_capital="EUR 10,000"),
        _profile(identity=2, document=11, filename="atto costitutivo.pdf", corporate_capital="EUR 20,000"),
    ]
    markdown = _render_corporate_intro(profiles, lang, ["Alfa S.r.l."])
    assert f"| {label} | EUR 10,000 |" in markdown
    assert "EUR 20,000" not in markdown
    assert "visura.pdf" in markdown and "atto costitutivo.pdf" in markdown
    assert warning in markdown
    assert label in markdown.split(warning)[0].rsplit("\n", 1)[-1]
    assert "\n- " not in markdown


def test_source_document_id_is_visible_when_filename_is_unavailable():
    markdown = _render_corporate_intro([_profile(filename=None)], "it", ["Alfa SRL"])
    assert "Documento #10" in markdown


@pytest.mark.parametrize("targets", [None, []])
def test_absent_scope_explicitly_requests_configuration_and_hides_legacy_profiles(targets):
    markdown = _render_corporate_intro([_profile()], "it", targets)
    assert "Società nel perimetro" in markdown
    assert "Alfa" not in markdown
    assert "### " not in markdown


def test_nonmatching_scope_has_clear_no_evidence_placeholder():
    markdown = _render_corporate_intro([_profile()], "en", ["Beta S.r.l."])
    assert "No corporate information matching" in markdown
    assert "Alfa" not in markdown
    assert "Companies without matching information:** Beta S.r.l." in markdown


@pytest.mark.parametrize("lang,label", [
    ("it", "Società senza informazioni corrispondenti"),
    ("en", "Companies without matching information"),
])
def test_partial_scope_explicitly_identifies_target_without_evidence(lang, label):
    markdown = _render_corporate_intro([_profile()], lang, ["Alfa SRL", "Beta SPA"])
    assert markdown.count("### ") == 1
    assert "### Alfa SRL" in markdown
    assert f"**{label}:** Beta SPA." in markdown
    assert "### Beta SPA" not in markdown


@pytest.mark.parametrize("lang,heading", [
    ("en", "Corporate Introductory Information"),
    ("it", "Informazioni Societarie"),
])
@pytest.mark.parametrize("numbered", [True, False])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_refresh_replaces_only_section_two_and_preserves_other_content(lang, heading, numbered, newline):
    prefix = "# Report\n\n**Titolo invariato**\n\n## 1. Introduction\n\nTesto esatto | è.\n\n"
    suffix = "## 3. Executive Summary\n\nProsa preesistente.\n\n## 4. Key Findings\n\n| A | B |\n\n## Appendix I\nfile.pdf\n"
    old_section = f"## {'2. ' if numbered else ''}{heading}\n\n### Vecchia società\nDa eliminare.\n\n"
    prefix, suffix, old_section = (part.replace("\n", newline) for part in (prefix, suffix, old_section))
    profiles = [_profile(registered_office="Milano"), _profile(identity=2, document=11, corporate_capital="EUR 10,000")]

    refreshed = refresh_corporate_intro_section(prefix + old_section + suffix, profiles, ["Alfa SRL"], lang)

    assert refreshed.startswith(prefix)
    assert refreshed.endswith(suffix)
    assert "Vecchia società" not in refreshed and "Da eliminare" not in refreshed
    assert "Milano" in refreshed and "EUR 10,000" in refreshed
    assert ("### 2.1 Alfa SRL" if numbered else "### Alfa SRL") in refreshed
    assert refreshed.count("## 3. Executive Summary") == 1
    assert refresh_corporate_intro_section(refreshed, profiles, ["Alfa SRL"], lang) == refreshed


@pytest.mark.parametrize("content", [
    "## Introduction\nNothing to replace\n## Executive Summary\nKeep",
    "## 1. Intro\n## 2. Corporate Introductory Information\n## 3. Executive Summary\n## 2. Informazioni Societarie\n## 4. Findings",
    "## 1. Intro\n## 3. Corporate Introductory Information\n## 4. Findings",
    "## 2. Corporate Introductory Information\n## 3. Executive Summary",
    "## 1. Intro\n## 2. Corporate Introductory Information\nNo later heading",
    "## 1. Intro\n## 2. Unknown custom section\n## 3. Executive Summary",
])
def test_refresh_fails_closed_for_missing_or_ambiguous_layout(content):
    with pytest.raises(ValueError):
        refresh_corporate_intro_section(content, [_profile()], ["Alfa SRL"], "en")


def test_only_corporate_records_raise_the_note_under_the_table():
    profiles = [
        _profile(business="Produzione di nastri trasportatori", filename="1-3-10.Visura aggiornata 2022.pdf"),
        _profile(identity=2, document=11, filename="2.1.nuovo statuto .pdf",
                 business="La produzione e la trasformazione di articoli tecnici industriali"),
        _profile(identity=3, document=12, filename="BPM 04582087.pdf",
                 business="Sostegno dell'attività aziendale"),
        _profile(identity=4, document=13, filename="bil2018-1129_view.pdf", fiscal_year="31/12/2018"),
        _profile(identity=5, document=14, filename="redditi sc 2021.pdf", fiscal_year="31/12/2020"),
    ]

    markdown = _render_corporate_intro(profiles, "it", ["Alfa S.r.l."])

    assert "\n- " not in markdown
    assert "Sostegno" not in markdown
    note = markdown.split("valori diversi per:")[1].split(".")[0]
    assert "Oggetto Sociale" in note and "Esercizio Sociale" not in note
