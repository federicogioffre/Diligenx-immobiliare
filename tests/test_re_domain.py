"""Real-estate domain tables: checklist, document types, areas, dated rules."""
import re
from datetime import date

import pytest

from packages.real_estate import areas, checklist, document_types, rules_registry as rr


# ── Checklist ────────────────────────────────────────────────────────────────

def test_checklist_keys_are_unique_and_sections_known():
    keys = [item["key"] for item in checklist.CHECKLIST]
    assert len(keys) == len(set(keys))
    for item in checklist.CHECKLIST:
        assert item["section_code"] in checklist.SECTIONS_ORDER
        assert item["key"].startswith(item["section_code"] + ".")
        assert item["area"] in areas.VALID_AREAS
        assert item["keywords"] and item["request_it"] and item["request_en"]


@pytest.mark.parametrize("filename,text,expected", [
    ("Visura_storica_Foglio12.pdf", "", "C.1"),
    ("planimetria.pdf", "", "C.2"),
    ("doc.pdf", "ATTESTATO DI PRESTAZIONE ENERGETICA degli edifici", "F.1"),
    ("SCIA 2015.pdf", "", "D.1"),
    ("ispezione_ipotecaria_rossi.pdf", "", "B.1"),
    ("doc.pdf", "Domanda di condono edilizio presentata nel 1986", "D.2"),
    ("Verbale assemblea 2025.pdf", "", "E.2"),
])
def test_documents_match_their_item(filename, text, expected):
    assert expected in checklist.matched_keys(filename, text)


@pytest.mark.parametrize("filename,text,not_expected", [
    # Short keywords must match whole words only.
    ("doc.pdf", "apertura della finestra", "F.1"),
    ("doc.pdf", "il venditore lascia l'immobile", "D.1"),
    # A preliminary contract mentions the sale but is not the title deed.
    ("preliminare.pdf", "Contratto preliminare di compravendita, il rogito sarà stipulato", "A.1"),
    # A deed mentions the marital regime but is not the civil-status extract.
    ("atto.pdf", "coniugato in regime di separazione dei beni", "H.2"),
])
def test_keywords_do_not_overmatch(filename, text, not_expected):
    assert not_expected not in checklist.matched_keys(filename, text)


# ── Document types ───────────────────────────────────────────────────────────

def test_unknown_document_type_becomes_other():
    assert document_types.normalize_document_type("visura_catastale") == "visura_catastale"
    assert document_types.normalize_document_type("Visura Catastale") == "visura_catastale"
    assert document_types.normalize_document_type("contract") == "other"
    assert document_types.normalize_document_type(None) == "other"


def test_classification_prompt_formats():
    prompt = document_types.DOCUMENT_CLASSIFICATION_PROMPT.format(filename="a.pdf", text="x")
    assert "CLASSIFY" in prompt and "atto_provenienza" in prompt


def test_areas_exist_in_the_enum():
    from app.models.red_flag import DueDiligenceArea
    for key in areas.AREA_ORDER:
        assert DueDiligenceArea(key).value == key
        assert key in areas.AREA_TITLES["it"] and key in areas.AREA_TITLES["en"]
    assert areas.parse_area("encumbrances").value == "encumbrances"
    assert areas.parse_area("corporate") is None


# ── Rules registry ───────────────────────────────────────────────────────────

def test_glosses_carry_no_amount_or_rate():
    money = re.compile(r"€|\beur(o)?\b|\d+\s*%|\bper cento\b|\bpercent\b", re.IGNORECASE)
    for versions in rr.RULES.values():
        for rule in versions:
            assert not money.search(rule.gloss_it), rule.rule_id
            assert not money.search(rule.gloss_en), rule.rule_id


def test_versions_do_not_overlap():
    for rule_id, versions in rr.RULES.items():
        for earlier, later in zip(versions, versions[1:]):
            assert earlier.valid_to is not None and earlier.valid_to < later.valid_from, rule_id


def test_resolve_by_date():
    assert "D.P.R. 380/2001" in rr.citation("building_title_mention", date(2020, 1, 1))
    assert rr.citation("building_title_mention", date(1990, 1, 1)) == "Art. 40 L. 47/1985"
    assert rr.resolve("cadastral_conformity", date(2009, 1, 1)) is None
    assert "L. 220/2012" in rr.citation("condominium_arrears", date(2024, 1, 1))


@pytest.mark.parametrize("raw,expected", [
    ("2015-03-12", date(2015, 3, 12)),
    ("12/03/2015", date(2015, 3, 12)),
    ("12.03.2015", date(2015, 3, 12)),
    ("12 marzo 2015", date(2015, 3, 12)),
    ("1° settembre 1967", date(1967, 9, 1)),
    ("marzo 2015", None),
    ("31/02/2015", None),
    (None, None),
])
def test_parse_date(raw, expected):
    assert rr.parse_date(raw) == expected


def test_donation_window():
    exposure = rr.donation_exposure(date(2015, 3, 12), as_of=date(2026, 10, 16))
    assert exposure.open and exposure.window_ends == date(2035, 3, 12)
    assert not rr.donation_exposure(date(2000, 1, 1), as_of=date(2026, 10, 16)).open


def test_mortgage_lapse_and_leap_day():
    assert rr.add_years(date(2004, 2, 29), 1) == date(2005, 2, 28)
    assert rr.mortgage_registration_lapsed(date(2004, 2, 29), as_of=date(2024, 2, 29))
    assert not rr.mortgage_registration_lapsed(date(2004, 2, 29), as_of=date(2024, 2, 28))
    assert not rr.mortgage_registration_lapsed(date(2010, 5, 1), as_of=date(2026, 10, 16))


def test_chain_coverage():
    as_of = date(2026, 10, 16)
    assert rr.chain_coverage([date(2001, 1, 1), date(2015, 1, 1)], as_of).covered
    gap = rr.chain_coverage([date(2015, 1, 1)], as_of)
    assert not gap.covered and gap.required_from == date(2006, 10, 16)
    assert not rr.chain_coverage([], as_of).covered
