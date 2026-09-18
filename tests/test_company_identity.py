"""Pure identity/consolidation regressions; no model or database imports."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from packages.agents.company_identity import consolidate_company_profiles, normalize_company_name


def profile(identity, name="TargetCo S.p.A.", source_id=None, **values):
    data = dict(id=identity, deal_id=4, company_name=name, source_document_id=source_id,
                created_at=datetime(2026, 9, 18, tzinfo=timezone.utc), confidence=0.9)
    data.update(values)
    return SimpleNamespace(**data)


@pytest.mark.parametrize("name", [" ALFA  S.R.L. ", "Alfa srl", "ALFA S. R. L.", "Alfa\u00a0S.r.l."])
def test_equivalent_legal_form_formatting(name):
    assert normalize_company_name(name) == "alfa srl"


def test_normalization_never_drops_identity_tokens_or_legal_form():
    names = ["Alfa Srl", "Alfa Spa", "Alfa Servizi Srl", "Alfa Srls", "Alfa", "Alfabet Srl"]
    assert len({normalize_company_name(name) for name in names}) == len(names)
    assert normalize_company_name("A&B Srl") != normalize_company_name("A B Srl")
    assert normalize_company_name("Società S.p.A.") == normalize_company_name("Societa\u0300 SPA")
    assert normalize_company_name(None) == ""


@pytest.mark.parametrize("scope", [None, [], ["", "  "], "TargetCo S.p.A."])
def test_missing_scope_never_consumes_or_returns_candidates(scope):
    def never_read():
        raise AssertionError("Missing scope must not access profile data")
        yield
    assert consolidate_company_profiles(never_read(), scope) == []


def test_only_exact_confirmed_targets_appear_in_requested_order():
    rows = [profile(1), profile(2, "Customer Srl"), profile(3, "Supplier Srl"),
            profile(4, "TargetCo Servizi S.p.A."), profile(5, "TargetCo Srl"),
            profile(6, "Holding S.R.L.")]
    result = consolidate_company_profiles(rows, ["Holding srl", "TARGETCO SPA", "TargetCo S.p.A."])
    assert [item.company_name for item in result] == ["Holding srl", "TARGETCO SPA"]
    assert [item.id for item in result] == [6, 1]


def test_merges_complementary_fields_duplicate_values_and_keeps_sources():
    rows = [profile(12, "TARGETCO SPA", 20, corporate_capital="Euro 1.000.000", confidence=0.8,
                    source_document=SimpleNamespace(filename="statuto.pdf")),
            profile(10, source_id=18, registered_office="Milano", shareholders="Holding Srl — 100%",
                    source_document=SimpleNamespace(filename="visura.pdf")),
            profile(11, source_id=18, registered_office="  MILANO  ")]
    before = deepcopy(rows)
    result = consolidate_company_profiles(rows, ["TargetCo S.p.A."])
    assert len(result) == 1
    combined = result[0]
    assert (combined.id, combined.deal_id, combined.source_document_id) == (10, 4, 18)
    assert combined.created_at == rows[1].created_at
    assert combined.registered_office == "Milano"
    assert combined.corporate_capital == "Euro 1.000.000"
    assert combined.shareholders == "Holding Srl — 100%"
    assert combined.confidence == 0.8
    assert combined.source_document_ids == [18, 20]
    assert combined.source_filenames == ["visura.pdf", "statuto.pdf"]
    assert combined.conflicting_fields == []
    assert rows == before


def test_conflicting_values_are_preserved_flagged_and_stable_under_input_reordering():
    rows = [profile(3, source_id=30, corporate_capital="Euro 20.000", registered_office="Roma",
                    shareholders="Alice — 50%\nBob — 50%", source_filename="later.pdf"),
            profile(1, source_id=10, corporate_capital="Euro 10.000", registered_office="Milano",
                    shareholders="Alice — 50%\nCarlo — 50%", source_filename="earlier.pdf")]
    forward = consolidate_company_profiles(rows, ["TargetCo S.p.A."])[0]
    reverse = consolidate_company_profiles(reversed(rows), ["TargetCo S.p.A."])[0]
    assert vars(forward) == vars(reverse)
    assert forward.corporate_capital == "Euro 10.000\nEuro 20.000"
    assert forward.registered_office == "Milano\nRoma"
    assert forward.shareholders == "Alice — 50%\nCarlo — 50%\nBob — 50%"
    assert forward.conflicting_fields == ["registered_office", "corporate_capital", "shareholders"]
    assert forward.field_sources["corporate_capital"] == [
        {"value": "Euro 10.000", "source_document_ids": [10], "source_filenames": ["earlier.pdf"], "profile_ids": [1]},
        {"value": "Euro 20.000", "source_document_ids": [30], "source_filenames": ["later.pdf"], "profile_ids": [3]},
    ]


def test_duplicate_values_retain_each_supporting_document_without_guessing_equivalence():
    rows = [profile(1, source_id=10, corporate_capital="EUR 10.000", source_filename="a.pdf"),
            profile(2, source_id=20, corporate_capital=" eur  10.000 ", source_filename="b.pdf"),
            profile(3, source_id=30, corporate_capital="10,000 euros", source_filename="c.pdf")]
    combined = consolidate_company_profiles(rows, ["TargetCo S.p.A.", "TARGETCO SPA"])[0]
    assert combined.field_sources["corporate_capital"][0] == {
        "value": "EUR 10.000", "source_document_ids": [10, 20],
        "source_filenames": ["a.pdf", "b.pdf"], "profile_ids": [1, 2],
    }
    assert combined.conflicting_fields == ["corporate_capital"]
    assert combined.corporate_capital == "EUR 10.000\n10,000 euros"


def test_never_lazy_loads_unavailable_source_document():
    class DetachedProfile:
        def __init__(self):
            self.__dict__.update(vars(profile(1, source_id=8)))

        @property
        def source_document(self):
            raise AssertionError("Must not lazy-load ORM relation")

    item = consolidate_company_profiles([DetachedProfile()], ["TargetCo SPA"])[0]
    assert item.source_document_ids == [8]
    assert item.source_filenames == []


def test_missing_source_and_confidence_are_allowed_without_losing_a_profile():
    result = consolidate_company_profiles([profile(1, confidence=None)], ["TargetCo SPA"])[0]
    assert result.confidence is None
    assert result.source_document_id is None
    assert result.source_document_ids == []
    assert result.source_filenames == []
